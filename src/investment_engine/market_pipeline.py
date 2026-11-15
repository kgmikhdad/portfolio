"""Research-only incremental Yahoo ingestion; membership/model gates never authorize orders."""

import csv
import hashlib
import io
import json
import math
import re
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as walltime
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yfinance as yf
from pypdf import PdfReader
from sqlalchemy import Engine, func, select, text

from investment_engine.broker import reconcile
from investment_engine.data import (
    IST,
    DataUnavailable,
    PriceBar,
    digest,
    paise,
    persist_actions,
    persist_bars,
    point_in_time_bars,
)
from investment_engine.db import transaction
from investment_engine.features import technical
from investment_engine.models import Account, Bar, Feature, Identifier, Job, Security
from investment_engine.reference import valid_isin

ROOT = Path(__file__).resolve().parents[2]
FEATURE_VERSION = "backend-technical-v1"
NSE_MASTER = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"


def load_registry(path: Path = ROOT / "config/research_universe.json") -> dict[str, Any]:
    config: dict[str, Any] = json.loads(path.read_text())
    records = config["securities"]
    if not records or len({r["isin"] for r in records}) != len(records):
        raise DataUnavailable("Reference universe is empty or contains duplicate ISINs")
    if len({r["symbol"] for r in records}) != len(records):
        raise DataUnavailable("Duplicate exchange symbols")
    if any(not valid_isin(r["isin"]) or r["series"] not in ("EQ", "BE") for r in records):
        raise DataUnavailable("Invalid reference security contract")
    return config


def factsheet_evidence() -> dict[str, Any]:
    url = "https://www.niftyindices.com/Factsheet/Factsheet_Nifty500_Shariah.pdf"
    try:
        response = httpx.get(url, timeout=25)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF") or len(response.content) > 5000000:
            raise ValueError("Unexpected factsheet response")
        page = (
            PdfReader(io.BytesIO(response.content)).pages[0].extract_text(extraction_mode="layout")
        )
        count = re.search(r"No\.\s*of\s*Constituents\s+(\d+)", page, re.I)
        date_match = re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", page)
        if count is None:
            raise ValueError("Factsheet layout changed")
        return {
            "official_factsheet_count": int(count.group(1)),
            "official_factsheet_date": date_match.group(0) if date_match else "unknown",
            "factsheet_source": url,
            "factsheet_sha256": hashlib.sha256(response.content).hexdigest(),
            "factsheet_status": "retrieved",
        }
    except Exception:
        return {"factsheet_status": "unavailable", "factsheet_source": url}


def reconcile_registry(config: dict[str, Any]) -> dict[str, Any]:
    factsheet = factsheet_evidence()
    try:
        response = httpx.get(NSE_MASTER, timeout=25)
        response.raise_for_status()
        master = [
            {k.strip(): v.strip() for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        ]
        by_symbol = {r["SYMBOL"]: r for r in master if r["SERIES"] in ("EQ", "BE")}
        mismatches = [
            r["symbol"]
            for r in config["securities"]
            if r["symbol"] not in by_symbol or by_symbol[r["symbol"]]["ISIN NUMBER"] != r["isin"]
        ]
        if mismatches:
            raise DataUnavailable("Current NSE identifiers changed; explicit review required")
        return {
            **factsheet,
            "status": "current_nse_master_verified",
            "source_hash": hashlib.sha256(response.content).hexdigest(),
            "universe_membership_verified": False,
        }
    except (httpx.HTTPError, KeyError, ValueError):
        received = datetime.fromisoformat(config["identifiers_retrieved_at"])
        if datetime.now(UTC) - received > timedelta(days=30):
            raise DataUnavailable(
                "Cached NSE identifiers expired; refresh reference configuration"
            ) from None
        return {
            **factsheet,
            "status": "cached_nse_identifiers_network_unavailable",
            "source_hash": config["identifier_source_sha256"],
            "universe_membership_verified": False,
        }


def frame_to_records(
    frame: Any, isin: str, received: int
) -> tuple[list[PriceBar], list[dict[str, Any]]]:
    required = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    if frame.empty or not required.issubset(frame.columns):
        raise DataUnavailable("Missing Yahoo OHLCV contract")
    bars, actions = [], []
    for index, row in frame.iterrows():
        day = index.date()
        published = int(datetime.combine(day, walltime(15, 30), IST).timestamp())
        if published > received:
            continue
        volume = float(row["Volume"])
        if not math.isfinite(volume) or volume < 0 or not volume.is_integer():
            raise DataUnavailable("Invalid provider volume")
        bars.append(
            PriceBar(
                isin=isin,
                day=day,
                source="yfinance-research",
                open_paise=paise(row["Open"]),
                high_paise=paise(row["High"]),
                low_paise=paise(row["Low"]),
                close_paise=paise(row["Close"]),
                adjusted_close_paise=paise(row["Adj Close"]),
                volume=int(volume),
                published_at=published,
                received_at=received,
            )
        )
        for column, kind in (("Dividends", "dividend"), ("Stock Splits", "split")):
            value = float(row.get(column, 0))
            if value:
                if not math.isfinite(value) or value < 0:
                    raise DataUnavailable("Invalid corporate-action value")
                ratio = Fraction(str(value)).limit_denominator(100000)
                actions.append(
                    {
                        "id": digest(
                            {
                                "source": "yfinance-research",
                                "isin": isin,
                                "day": str(day),
                                "kind": kind,
                                "value": str(value),
                            }
                        ),
                        "isin": isin,
                        "kind": kind,
                        "effective_at": int(index.timestamp()),
                        "published_at": received,
                        "received_at": received,
                        "numerator": ratio.numerator if kind == "split" else None,
                        "denominator": ratio.denominator if kind == "split" else None,
                        "cash_paise": paise(value) if kind == "dividend" else None,
                        "source": "yfinance-research:ex-date-unreconciled",
                    }
                )
    if [b.day for b in bars] != sorted({b.day for b in bars}):
        raise DataUnavailable("Provider sessions must be sorted and unique")
    if not bars or received - bars[-1].published_at > 7 * 86400:
        raise DataUnavailable("No sufficiently recent completed daily bar")
    return bars, actions


def download_history(
    symbol: str, isin: str, last_day: str | None, backfill: bool = False
) -> tuple[list[PriceBar], list[dict[str, Any]]]:
    ticker = yf.Ticker(symbol + ".NS")
    options: dict[str, Any] = {
        "auto_adjust": False,
        "actions": True,
        "repair": False,
        "timeout": 20,
    }
    if backfill or last_day is None:
        options["period"] = "5y"
    else:
        options["start"] = (date.fromisoformat(last_day) - timedelta(days=14)).isoformat()
    frame = ticker.history(**options)
    metadata = ticker.history_metadata
    if metadata.get("currency") != "INR" or metadata.get("symbol") != symbol + ".NS":
        raise DataUnavailable("Yahoo identifier/currency mismatch")
    # A newly observed action changes Yahoo's back-adjusted history. Refresh a coherent vintage.
    if (
        last_day
        and not backfill
        and not frame.empty
        and any(
            float(frame.get(name, []).sum()) != 0
            for name in ("Dividends", "Stock Splits")
            if name in frame.columns
        )
    ):
        frame = ticker.history(
            period="5y", auto_adjust=False, actions=True, repair=False, timeout=20
        )
    return frame_to_records(frame, isin, int(time.time()))


def research_features(bars: list[Bar]) -> dict[str, Any]:
    if not bars or any(b.adjusted_close_paise is None for b in bars):
        raise DataUnavailable("Coherent adjusted-close history required")
    prices = [float(b.adjusted_close_paise or 0) for b in bars]
    result: dict[str, Any] = technical(prices)
    for horizon in (20, 60, 120, 250):
        result[f"momentum{horizon}"] = (
            prices[-1] / prices[-horizon - 1] - 1 if len(prices) > horizon else None
        )
    result["mean_turnover20_inr"] = (
        sum(b.close_paise * b.volume / 100 for b in bars[-20:]) / 20 if len(bars) >= 20 else None
    )
    result.update(
        {
            "last_session": bars[-1].day,
            "close_inr": bars[-1].close_paise / 100,
            "observations": len(bars),
            "universe_verified": False,
            "signal_type": "independent_price_only_research",
            "model_approved": False,
            "trade_approved": False,
            "fundamentals_available": False,
            "missing_requirements": [
                "verified_index_membership",
                "fundamentals",
                "validated_strategy",
                "official_session_calendar",
            ],
        }
    )
    return result


def ingest_market(db: Engine, *, backfill: bool = False, limit: int = 0) -> dict[str, Any]:
    config = load_registry()
    reference = reconcile_registry(config)
    records = config["securities"][:limit] if limit > 0 else config["securities"]
    job_id = "market-" + uuid4().hex
    started = int(time.time())
    cache = ROOT / "var/cache/yfinance"
    cache.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache))
    with transaction(db) as session:
        account = session.get(Account, "paper")
        if account is None or not account.stopped:
            raise DataUnavailable("Initialized paper account with active emergency stop required")
        reconcile(session, "paper")
        known = {s.isin: s for s in session.scalars(select(Security))}
        for record in records:
            security = known.get(record["isin"])
            if security is None:
                session.add(
                    Security(
                        isin=record["isin"], symbol=record["symbol"], sector=record["industry"]
                    )
                )
            elif security.symbol != record["symbol"]:
                raise DataUnavailable("Existing security identifier mismatch")
        session.flush()
        identifiers = set(
            session.scalars(
                select(Identifier.isin).where(
                    Identifier.provider == "yahoo", Identifier.valid_to.is_(None)
                )
            )
        )
        for record in records:
            if record["isin"] not in identifiers:
                session.add(
                    Identifier(
                        isin=record["isin"],
                        provider="yahoo",
                        symbol=record["symbol"] + ".NS",
                        valid_from=started,
                        source=config["verified_identifier_source"],
                    )
                )
        last_days = dict(
            session.execute(select(Bar.isin, func.max(Bar.day)).group_by(Bar.isin)).all()
        )
        session.add(
            Job(
                id=job_id,
                started_at=started,
                status="running",
                details={
                    "kind": "market_ingestion",
                    "requested": len(records),
                    "reference": reference,
                },
            )
        )
    succeeded, inserted, consecutive = 0, 0, 0
    failures: list[dict[str, str]] = []
    status = "failed"
    try:
        for record in records:
            if consecutive >= 3:
                failures.extend(
                    {"symbol": r["symbol"], "reason": "ingestion_circuit_open"}
                    for r in records[succeeded + len(failures) :]
                )
                break
            try:
                bars, actions = download_history(
                    record["symbol"], record["isin"], last_days.get(record["isin"]), backfill
                )
                with transaction(db) as session:
                    if db.dialect.name == "postgresql":
                        used: int = session.execute(
                            text("SELECT pg_database_size(current_database())")
                        ).scalar_one()
                        if used > 400 * 1024 * 1024:
                            raise DataUnavailable("Research storage safety limit reached")
                    added = persist_bars(session, bars)
                    persist_actions(session, actions)
                    available = point_in_time_bars(session, record["isin"], int(time.time()))
                    values = research_features(available)
                    dataset_hash = digest([b.content_hash for b in available])
                    existing = session.scalar(
                        select(Feature.id).where(
                            Feature.isin == record["isin"],
                            Feature.definition_version == FEATURE_VERSION,
                            Feature.dataset_hash == dataset_hash,
                        )
                    )
                    if existing is None:
                        session.add(
                            Feature(
                                isin=record["isin"],
                                definition_version=FEATURE_VERSION,
                                as_of=int(time.time()),
                                values=values,
                                dataset_hash=dataset_hash,
                            )
                        )
                inserted += added
                succeeded += 1
                consecutive = 0
            except Exception as error:
                failures.append(
                    {
                        "symbol": record["symbol"],
                        "reason": str(error)
                        if isinstance(error, DataUnavailable)
                        else type(error).__name__,
                    }
                )
                consecutive += 1
            if (succeeded + len(failures)) % 10 == 0:
                with transaction(db) as session:
                    job = session.get(Job, job_id)
                    assert job is not None
                    job.details = {
                        "kind": "market_ingestion",
                        "requested": len(records),
                        "succeeded": succeeded,
                        "failures": failures,
                        "reference": reference,
                    }
            time.sleep(1)  # Single-worker, modest request pacing; no proxy/account rotation.
        status = "ingested" if not failures else "partial" if succeeded else "blocked"
    except Exception:
        status = "failed"
        raise
    finally:
        with transaction(db) as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.status, job.finished_at = status, int(time.time())
            job.details = {
                "kind": "market_ingestion",
                "requested": len(records),
                "succeeded": succeeded,
                "failures": failures,
                "new_bars": inserted,
                "reference": reference,
                "universe_verified": False,
                "orders_executed": 0,
            }
    return {
        "job_id": job_id,
        "status": status,
        "requested": len(records),
        "succeeded": succeeded,
        "failed": len(failures),
        "failure_examples": failures[:5],
        "new_bars": inserted,
        "universe_verified": False,
        "orders_executed": 0,
    }
