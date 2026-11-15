"""Read-only views of hosted research and ledger data; no workbook scores are substituted."""

import time
from typing import Any

from sqlalchemy import Engine, func, select

from investment_engine.db import transaction
from investment_engine.market_pipeline import FEATURE_VERSION
from investment_engine.models import Bar, Experiment, Feature, Job, Order, Prediction, Security
from investment_engine.operations import portfolio_report


def dashboard_data(db: Engine) -> dict[str, Any]:
    report = portfolio_report(db, "paper", int(time.time()))
    with transaction(db) as session:
        securities = {row.isin: row for row in session.scalars(select(Security))}
        ranked = (
            select(
                Feature.id,
                func.row_number()
                .over(partition_by=Feature.isin, order_by=(Feature.as_of.desc(), Feature.id.desc()))
                .label("rank"),
            )
            .where(Feature.definition_version == FEATURE_VERSION)
            .subquery()
        )
        features = session.scalars(
            select(Feature).join(ranked, ranked.c.id == Feature.id).where(ranked.c.rank == 1)
        ).all()
        research = []
        for feature in features:
            security = securities.get(feature.isin)
            if security:
                research.append(
                    {
                        "isin": feature.isin,
                        "symbol": security.symbol,
                        "industry": security.sector,
                        "as_of": feature.as_of,
                        "dataset_hash": feature.dataset_hash,
                        **feature.values,
                    }
                )
        orders = session.scalars(
            select(Order)
            .where(Order.account_id == "paper")
            .order_by(Order.executed_at.desc())
            .limit(200)
        ).all()
        report["executions"] = [
            {
                "id": o.id,
                "isin": o.isin,
                "side": o.side,
                "quantity": o.quantity,
                "price_paise": o.price_paise,
                "fees_paise": o.fees_paise,
                "executed_at": o.executed_at,
            }
            for o in orders
        ]
        job = session.scalar(
            select(Job).where(Job.id.like("market-%")).order_by(Job.started_at.desc())
        )
        bar_count: int = session.scalar(select(func.count()).select_from(Bar)) or 0
        latest_day: str | None = session.scalar(select(func.max(Bar.day)))
        experiments = session.scalars(
            select(Experiment).order_by(Experiment.created_at.desc())
        ).all()
        predictions = session.scalars(select(Prediction).order_by(Prediction.as_of.desc())).all()
        unique: dict[tuple[str, int], dict[str, Any]] = {}
        for prediction in predictions:
            key = prediction.isin, prediction.horizon
            if key not in unique:
                security = securities.get(prediction.isin)
                unique[key] = {
                    "symbol": security.symbol if security else prediction.isin,
                    "horizon": prediction.horizon,
                    "estimate": prediction.estimate,
                    "uncertainty": prediction.uncertainty,
                    "as_of": prediction.as_of,
                    "experiment_id": prediction.experiment_id,
                    "status": "experimental_not_approved",
                }
        return {
            "source": "backend_database",
            "portfolio": report,
            "research": research,
            "security_count": len(securities),
            "bar_count": bar_count,
            "latest_session": latest_day,
            "last_ingestion": (
                {
                    "id": job.id,
                    "status": job.status,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "details": job.details,
                }
                if job
                else None
            ),
            "predictions": list(unique.values()),
            "experiments": [
                {
                    "id": e.id,
                    "model_kind": e.model_kind,
                    "status": e.status,
                    "created_at": e.created_at,
                    "metrics": e.metrics,
                    "dataset_hash": e.dataset_hash,
                }
                for e in experiments
            ],
        }


def price_history(db: Engine, isin: str) -> list[dict[str, Any]]:
    with transaction(db) as session:
        rows = session.scalars(
            select(Bar)
            .where(Bar.isin == isin)
            .order_by(Bar.day.desc(), Bar.received_at.desc(), Bar.id.desc())
        ).all()
        by_day: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.day not in by_day:
                by_day[row.day] = {
                    "date": row.day,
                    "close_inr": row.close_paise / 100,
                    "adjusted_close_inr": (
                        row.adjusted_close_paise / 100 if row.adjusted_close_paise else None
                    ),
                    "volume": row.volume,
                    "source": row.source,
                }
        return [by_day[day] for day in sorted(by_day)]
