"""Isolated event-driven daily research simulation, next-session open execution."""

from dataclasses import asdict
from typing import Any, Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from investment_engine.actions import apply_action
from investment_engine.broker import (
    Costs,
    Proposal,
    Quote,
    RiskRejected,
    execute,
    initialize,
    reconcile,
)
from investment_engine.data import digest, point_in_time_bars
from investment_engine.features import technical
from investment_engine.models import (
    Account,
    Bar,
    CorporateAction,
    Holding,
    MarketSession,
    Membership,
    Security,
)
from investment_engine.settings import Settings


def metrics(navs: list[int], costs: int, turnover_paise: int) -> dict[str, Any]:
    if len(navs) < 2 or min(navs) <= 0:
        raise ValueError("At least two positive NAVs required")
    values = np.asarray(navs, dtype=np.float64)
    returns = values[1:] / values[:-1] - 1
    drawdown = 1 - values / np.maximum.accumulate(values)
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0) ** 2)))
    cagr = float((values[-1] / values[0]) ** (252 / len(returns)) - 1)
    maximum = float(np.max(drawdown))
    return {
        "absolute_return": float(values[-1] / values[0] - 1),
        "cagr": cagr if len(returns) >= 252 else None,
        "sharpe_zero_risk_free": float(np.mean(returns) / std * np.sqrt(252)) if std else None,
        "sortino_zero_target": (
            float(np.mean(returns) / downside * np.sqrt(252)) if downside else None
        ),
        "maximum_drawdown": maximum,
        "calmar": cagr / maximum if len(returns) >= 252 and maximum else None,
        "costs_paise": costs,
        "turnover_initial_nav": turnover_paise / navs[0],
        "observations": len(navs),
        "benchmark": None,
        "benchmark_status": "blocked: licensed total-return series not supplied",
    }


def run(
    session: Session, days: list[str], dataset_label: str, costs: Costs | None = None
) -> dict[str, Any]:
    costs = costs or Costs()
    if len(days) < 2 or days != sorted(set(days)):
        raise ValueError("Sorted unique simulation days required")
    # Caller must supply an isolated migrated database, never an operational ledger.
    if session.scalar(select(Account.id)) is not None:
        raise ValueError("Backtests require an empty isolated portfolio database")
    market_sessions = [session.get(MarketSession, day) for day in days]
    if any(m is None or not m.verified for m in market_sessions):
        raise ValueError("Verified exchange calendar required")
    first = market_sessions[0]
    assert first is not None
    account = initialize(session, "backtest", first.opens_at)
    account.stopped = False
    config = Settings(emergency_stop=False)
    navs, rejected, trades, total_costs, turnover = [account.cash_paise], [], [], 0, 0
    for index in range(1, len(days)):
        market, prior_session = market_sessions[index], market_sessions[index - 1]
        assert market is not None and prior_session is not None
        signal_at = prior_session.closes_at + 300
        for action in session.scalars(
            select(CorporateAction).where(
                CorporateAction.effective_at > prior_session.opens_at,
                CorporateAction.effective_at <= market.opens_at,
            )
        ):
            apply_action(session, account.id, action.id, market.opens_at)
        # Fill-only open values do not enter the previous-session feature calculation.
        rows = session.scalars(
            select(Bar).where(Bar.day == market.day).order_by(Bar.received_at, Bar.id)
        ).all()
        # Daily revisions cannot silently rewrite historical fills.
        by_isin: dict[str, Bar] = {}
        for row in rows:
            if row.isin in by_isin:
                raise ValueError("Ambiguous execution bar revisions/sources require reconciliation")
            by_isin[row.isin] = row
        quotes = {
            isin: Quote(
                isin,
                row.open_paise,
                market.opens_at,
                market.opens_at,
                "simulated-next-open:" + row.source,
            )
            for isin, row in by_isin.items()
        }
        for isin in sorted(by_isin):
            bars = point_in_time_bars(session, isin, signal_at)
            if len(bars) < 21:
                rejected.append(
                    {"day": market.day, "isin": isin, "reason": "insufficient PIT data"}
                )
                continue
            # Raw prices with unresolved corporate actions are never technical signals.
            unresolved = session.scalar(
                select(CorporateAction.id).where(
                    CorporateAction.isin == isin, CorporateAction.effective_at <= signal_at
                )
            )
            if unresolved:
                rejected.append(
                    {
                        "day": market.day,
                        "isin": isin,
                        "reason": "corporate-action-normalized signal series required",
                    }
                )
                continue
            feature = technical([float(b.close_paise) for b in bars])
            momentum = feature["momentum20"]
            holding = session.get(Holding, (account.id, isin))
            if momentum is None or (momentum <= 0 and (holding is None or not holding.quantity)):
                continue  # cash is a valid baseline decision
            if momentum > 0 and holding and holding.quantity:
                continue
            side: Literal["buy", "sell"] = "buy" if momentum > 0 else "sell"
            quantity = (
                int(account.initial_paise * 0.07) // quotes[isin].price_paise
                if side == "buy"
                else holding.quantity
                if holding
                else 0
            )
            if quantity <= 0:
                continue
            proposal = Proposal(
                f"{market.day}:{isin}",
                account.id,
                isin,
                side,
                quantity,
                signal_at,
                market.opens_at,
                "experimental momentum20 baseline",
            )
            try:
                order = execute(session, proposal, quotes, config, costs)
                total_costs += order.fees_paise
                turnover += order.quantity * order.price_paise
                trades.append(
                    {
                        "id": order.id,
                        "side": side,
                        "quantity": quantity,
                        "fees_paise": order.fees_paise,
                    }
                )
            except RiskRejected as error:
                rejected.append({"day": market.day, "isin": isin, "reason": str(error)})
        holdings = session.scalars(
            select(Holding).where(Holding.account_id == account.id, Holding.quantity > 0)
        ).all()
        if any(h.isin not in by_isin for h in holdings):
            raise ValueError("Missing closing valuation; simulation cannot continue")
        navs.append(
            account.cash_paise + sum(h.quantity * by_isin[h.isin].close_paise for h in holdings)
        )
        reconcile(session, account.id)
    dataset = {}
    for model in (Bar, Security, Membership, MarketSession, CorporateAction):
        records = [
            {c.name: getattr(row, c.name) for c in model.__table__.columns if c.name != "id"}
            for row in session.scalars(select(model))
        ]
        dataset[model.__tablename__] = sorted(records, key=digest)
    return {
        "status": "research-only",
        "dataset_label": dataset_label,
        "dataset_hash": digest(dataset),
        "fill_assumption": "next-session open plus adverse slippage; no fill guarantees",
        "cost_assumptions": asdict(costs),
        "trades": trades,
        "rejected": rejected,
        "navs_paise": navs,
        "metrics": metrics(navs, total_costs, turnover),
    }
