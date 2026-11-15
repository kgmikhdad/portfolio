from typing import Any

from sqlalchemy import Engine, select

from investment_engine.broker import reconcile
from investment_engine.db import transaction
from investment_engine.models import Job, MarketSession


def health(db: Engine, account_id: str, now: int, grace_seconds: int = 7200) -> dict[str, Any]:
    with transaction(db) as session:
        accounting = reconcile(session, account_id)
        latest_session = session.scalar(
            select(MarketSession)
            .where(
                MarketSession.verified.is_(True),
                MarketSession.closes_at <= now - grace_seconds,
            )
            .order_by(MarketSession.closes_at.desc())
        )
        latest_job = session.scalar(select(Job).order_by(Job.started_at.desc()))
        reasons = []
        if latest_session is None:
            reasons.append("no_verified_calendar")
        if latest_job is None:
            reasons.append("no_job_history")
        elif latest_job.status not in ("screened",):
            reasons.append("last_job_not_successful")
        elif latest_session and (
            latest_job.finished_at is None or latest_job.finished_at < latest_session.closes_at
        ):
            reasons.append("missed_after_market_run")
        return {
            "status": "blocked" if reasons else "healthy",
            "reasons": reasons,
            "accounting": accounting,
            "last_job": latest_job.id if latest_job else None,
        }
