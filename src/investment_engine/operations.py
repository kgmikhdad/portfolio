import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import Engine, select

from investment_engine.broker import initialize, reconcile
from investment_engine.data import IST, DataUnavailable, digest, point_in_time_bars
from investment_engine.db import transaction
from investment_engine.features import technical
from investment_engine.models import (
    Bar,
    CorporateAction,
    Decision,
    Feature,
    Holding,
    Job,
    MarketSession,
    Membership,
    Order,
    Security,
)


def portfolio_report(db: Engine, account_id: str, at: int) -> dict[str, Any]:
    with transaction(db) as session:
        accounting = reconcile(session, account_id)
        holdings = session.scalars(
            select(Holding).where(Holding.account_id == account_id, Holding.quantity > 0)
        ).all()
        orders = session.scalars(select(Order).where(Order.account_id == account_id)).all()
        return {
            "realized_pnl_paise": sum(o.realized_paise for o in orders),
            "transaction_fees_paise": sum(o.fees_paise for o in orders),
            "schema_version": "1",
            "mode": "paper",
            "account": account_id,
            "as_of": at,
            "currency": "INR",
            **accounting,
            "holdings": [
                {"isin": h.isin, "quantity": h.quantity, "cost_paise": h.cost_paise}
                for h in holdings
            ],
            "nav_paise": accounting["cash_paise"] if not holdings else None,
            "valuation_status": "cash-only" if not holdings else "requires fresh marks",
            "signal_type": "deterministic research; no approved model",
            "real_money_enabled": False,
        }


def daily_research(db: Engine, account_id: str, at: int) -> dict[str, Any]:
    """After-market screening. Execution is a separate verified next-session process.

    Reruns never issue trades; per-day decisions have deterministic identifiers.
    """
    job_id = str(uuid4())
    with transaction(db) as session:
        initialize(session, account_id, at)
        session.add(Job(id=job_id, started_at=int(time.time()), status="running", details={}))
    failures, candidates = [], []
    try:
        with transaction(db) as session:
            securities = session.scalars(select(Security).order_by(Security.isin)).all()
            if not securities:
                raise DataUnavailable("Security master is empty; verified universe required")
            day = datetime.fromtimestamp(at, IST).date().isoformat()
            market = session.get(MarketSession, day)
            if market is None or not market.verified:
                raise DataUnavailable("Verified exchange session calendar required")
            if at < market.closes_at + 300:
                raise DataUnavailable("After-market source finalization window not reached")
            for security in securities:
                bars = point_in_time_bars(session, security.isin, at)
                membership = session.scalar(
                    select(Membership.id).where(
                        Membership.isin == security.isin,
                        Membership.verified.is_(True),
                        Membership.index_name == "Nifty500 Shariah",
                        Membership.valid_from <= at,
                        Membership.valid_to > at,
                        Membership.published_at <= at,
                        Membership.received_at <= at,
                    )
                )
                actions = session.scalar(
                    select(CorporateAction.id).where(
                        CorporateAction.isin == security.isin, CorporateAction.effective_at <= at
                    )
                )
                if (
                    not membership
                    or len(bars) < 21
                    or at - bars[-1].published_at > 86400
                    or actions
                ):
                    failures.append(
                        {
                            "isin": security.isin,
                            "reason": "Required data or action normalization missing",
                        }
                    )
                    continue
                values = technical([float(b.close_paise) for b in bars])
                data_hash = digest([b.content_hash for b in bars])
                existing = session.scalar(
                    select(Feature.id).where(
                        Feature.isin == security.isin,
                        Feature.definition_version == "technical-v1",
                        Feature.as_of == at,
                        Feature.dataset_hash == data_hash,
                    )
                )
                if existing is None:
                    session.add(
                        Feature(
                            isin=security.isin,
                            definition_version="technical-v1",
                            as_of=at,
                            values=values,
                            dataset_hash=data_hash,
                        )
                    )
                decision_id = digest({"account": account_id, "isin": security.isin, "at": at})
                if session.get(Decision, decision_id) is None:
                    session.add(
                        Decision(
                            id=decision_id,
                            account_id=account_id,
                            isin=security.isin,
                            at=at,
                            kind="research_only",
                            reason="Unvalidated momentum baseline; no approved trade",
                            evidence={"features": values, "dataset_hash": data_hash},
                        )
                    )
                candidates.append(
                    {"isin": security.isin, "features": values, "status": "research_only"}
                )
            if not candidates:
                raise DataUnavailable("No security passed required data contracts")
        result: dict[str, Any] = {
            "status": "partial" if failures else "screened",
            "candidates": candidates,
            "blocked": failures,
            "orders_executed": 0,
        }
    except Exception as error:
        # Persist a failure independently of the rolled-back research transaction.
        with transaction(db) as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.status = "blocked" if isinstance(error, DataUnavailable) else "failed"
            job.finished_at = int(time.time())
            job.details = {"error_type": type(error).__name__, "blocked": failures}
        raise
    with transaction(db) as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.status, job.finished_at, job.details = result["status"], int(time.time()), result
    return {"job_id": job_id, **result}


def export_parquet(db: Engine, destination: Path) -> int:
    with transaction(db) as session:
        rows = [
            {column.name: getattr(bar, column.name) for column in Bar.__table__.columns}
            for bar in session.scalars(select(Bar).order_by(Bar.id))
        ]
    if not rows:
        raise DataUnavailable("No observations to archive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), destination, compression="zstd")
    destination.with_suffix(".manifest.json").write_text(
        json.dumps({"rows": len(rows), "data_hash": digest(rows), "format": "bars-v1"}, indent=2)
    )
    return len(rows)


class SheetsDashboard:
    """Explicit token handoff; never modifies source tabs. Backup is a prerequisite."""

    def __init__(self, access_token: str, spreadsheet_id: str) -> None:
        self.client = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {access_token}"})
        self.sheet = spreadsheet_id

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise DataUnavailable(f"Google API HTTP {response.status_code}; no success recorded")
        result: dict[str, Any] = response.json()
        return result

    def backup(self) -> str:
        data = self._request(
            "POST",
            f"https://www.googleapis.com/drive/v3/files/{self.sheet}/copy",
            json={"name": f"Investment original backup {int(time.time())}"},
        )
        backup_id = data.get("id")
        if not backup_id:
            raise DataUnavailable("Google Drive backup not confirmed")
        # Verify the actual backup resource before permitting any dashboard writes.
        verified = self._request(
            "GET",
            f"https://www.googleapis.com/drive/v3/files/{backup_id}",
            params={"fields": "id,mimeType,trashed"},
        )
        if (
            verified.get("trashed")
            or verified.get("mimeType") != "application/vnd.google-apps.spreadsheet"
        ):
            raise DataUnavailable("Backup resource verification failed")
        return str(backup_id)

    def sync(self, report: dict[str, Any], backup_id: str) -> None:
        if not backup_id or backup_id == self.sheet:
            raise ValueError("A distinct verified original backup is required")
        self._request(
            "GET", f"https://www.googleapis.com/drive/v3/files/{backup_id}", params={"fields": "id"}
        )
        base = f"https://sheets.googleapis.com/v4/spreadsheets/{self.sheet}"
        metadata = self._request("GET", base, params={"fields": "sheets.properties"})
        title = "AIE_Backend_Status_v1"
        if any(s["properties"]["title"] == title for s in metadata.get("sheets", [])):
            # Do not overwrite pre-existing user tabs, even if the name resembles our prefix.
            title += "_" + str(int(time.time()))
        self._request(
            "POST",
            base + ":batchUpdate",
            json={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )
        rows = [
            ["field", "backend value"],
            *[[key, json.dumps(value, default=str)] for key, value in sorted(report.items())],
        ]
        self._request(
            "PUT",
            base + f"/values/{title}!A1",
            params={"valueInputOption": "RAW"},
            json={"values": rows},
        )
