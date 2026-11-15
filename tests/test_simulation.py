from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import ISIN, timestamp
from sqlalchemy import select

from investment_engine.actions import apply_action
from investment_engine.backtest import run
from investment_engine.broker import Proposal, Quote, RiskRejected, execute, reconcile
from investment_engine.data import PriceBar, persist_bars
from investment_engine.db import transaction
from investment_engine.models import (
    Account,
    ActionPosting,
    CorporateAction,
    Holding,
    MarketSession,
    Membership,
    Security,
)
from investment_engine.settings import Settings


def test_sector_limit_and_all_holdings_marks(db, market):
    signal, at = market
    from investment_engine.models import Bar

    quotes = {ISIN: Quote(ISIN, 10000, at, at, "synthetic")}
    isins = [ISIN, "INE000B01010", "INE000C01010", "INE000D01010"]
    with transaction(db) as session:
        prior = session.scalar(select(Bar))
        for index, isin in enumerate(isins[1:]):
            session.add(Security(isin=isin, symbol=f"SYNTHETIC{index}", sector="test-sector"))
            session.flush()
            session.add(
                Membership(
                    isin=isin,
                    valid_from=signal - 1000,
                    valid_to=at + 10000,
                    published_at=signal - 1000,
                    received_at=signal - 999,
                    source="synthetic",
                    document_hash=isin,
                    verified=True,
                )
            )
            session.add(
                Bar(
                    **{
                        c.name: getattr(prior, c.name)
                        for c in Bar.__table__.columns
                        if c.name not in ("id", "isin")
                    },
                    isin=isin,
                )
            )
            quotes[isin] = Quote(isin, 10000, at, at, "synthetic")
        session.flush()
        for i, isin in enumerate(isins[:3]):
            execute(
                session,
                Proposal(str(i), "test", isin, "buy", 70, signal, at, "test"),
                quotes,
                Settings(emergency_stop=False),
            )
        with pytest.raises(RiskRejected, match="Sector"):
            execute(
                session,
                Proposal("fourth", "test", isins[3], "buy", 70, signal, at, "test"),
                quotes,
                Settings(emergency_stop=False),
            )
        assert reconcile(session, "test")["positions"] == 3
        with pytest.raises(RiskRejected, match="portfolio mark"):
            execute(
                session,
                Proposal("missing-mark", "test", ISIN, "buy", 1, signal, at, "test"),
                {ISIN: quotes[ISIN]},
                Settings(emergency_stop=False),
            )


def test_participation_boundary(db, market):
    from investment_engine.models import Bar

    signal, at = market
    with transaction(db) as session:
        session.scalar(select(Bar)).volume = 1000
        session.flush()
        proposal = Proposal("limit", "test", ISIN, "buy", 11, signal, at, "test")
        with pytest.raises(RiskRejected, match="Participation"):
            execute(
                session,
                proposal,
                {ISIN: Quote(ISIN, 10000, at, at, "test")},
                Settings(emergency_stop=False, minimum_daily_turnover=Decimal("0")),
            )


def test_split_preserves_basis_and_is_idempotent(db, market):
    signal, at = market
    with transaction(db) as session:
        execute(
            session,
            Proposal("buy", "test", ISIN, "buy", 50, signal, at, "test"),
            {ISIN: Quote(ISIN, 10000, at, at, "test")},
            Settings(emergency_stop=False),
        )
        basis = session.get(Holding, ("test", ISIN)).cost_paise
        session.add(
            CorporateAction(
                id="split",
                isin=ISIN,
                kind="split",
                effective_at=at + 86400,
                published_at=signal,
                received_at=signal,
                numerator=2,
                denominator=1,
                source="synthetic",
            )
        )
    with transaction(db) as session:
        apply_action(session, "test", "split", at + 86400)
        apply_action(session, "test", "split", at + 86400)
        holding = session.get(Holding, ("test", ISIN))
        assert holding.quantity == 100 and holding.cost_paise == basis
        assert reconcile(session, "test")["orders"] == 1
        assert len(session.scalars(select(ActionPosting)).all()) == 1


def seed_backtest(db):
    days = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(30)]
    # Synthetic sessions deliberately do not assert a real-world exchange holiday calendar.
    with transaction(db) as session:
        session.add(Security(isin=ISIN, symbol="SYNTHETIC", sector="test-sector"))
        session.flush()
        start, end = timestamp(days[0], 9), timestamp(days[-1], 16)
        session.add(
            Membership(
                isin=ISIN,
                valid_from=start - 1,
                valid_to=end + 1,
                published_at=start - 2,
                received_at=start - 1,
                verified=True,
                document_hash="synthetic",
                source="synthetic",
            )
        )
        for i, day in enumerate(days):
            opening, closing = timestamp(day, 9, 15), timestamp(day, 15, 30)
            session.add(
                MarketSession(
                    day=day, opens_at=opening, closes_at=closing, verified=True, source="synthetic"
                )
            )
            price = 10000 + i * 50
            persist_bars(
                session,
                [
                    PriceBar(
                        isin=ISIN,
                        day=day,
                        source="synthetic",
                        open_paise=price,
                        close_paise=price + 10,
                        high_paise=price + 100,
                        low_paise=price - 100,
                        volume=1000000,
                        published_at=closing,
                        received_at=closing + 60,
                    )
                ],
            )
    return days


def test_backtest_reproducible_realistic_timing_and_cash(db):
    days = seed_backtest(db)
    with transaction(db) as session:
        result = run(session, days, "SYNTHETIC TEST ONLY")
        assert result["trades"] and result["trades"][0]["id"].startswith(days[21])
        assert result["metrics"]["costs_paise"] > 0
        assert result["metrics"]["benchmark"] is None
        assert result["metrics"]["cagr"] is None  # short runs do not annualize as evidence
        assert session.get(Account, "backtest").cash_paise >= 0
    # Reproduce from identical fixed input in an independent fresh SQLite database.
    from investment_engine.db import engine
    from investment_engine.models import Base

    other = engine("sqlite:///:memory:")
    Base.metadata.create_all(other)
    seed_backtest(other)
    with transaction(other) as session:
        second = run(session, days, "SYNTHETIC TEST ONLY")
    assert result == second
    other.dispose()


def test_backtest_missing_exchange_session_fails(db):
    days = seed_backtest(db)
    with transaction(db) as session:
        session.get(MarketSession, days[2]).verified = False
        session.flush()
        with pytest.raises(ValueError, match="calendar"):
            run(session, days, "synthetic")


def test_gym_environment_contract_and_constraints(db):
    import numpy as np
    from gymnasium.utils.env_checker import check_env

    from investment_engine.rl import PortfolioEnv

    days = seed_backtest(db)
    with transaction(db) as session:
        env = PortfolioEnv(session, days, "SYNTHETIC TEST ONLY")
    check_env(env, skip_render_check=True)
    observation, _ = env.reset(seed=42)
    assert env.observation_space.contains(observation)
    rejected = 0
    for _ in range(len(days) - 1):
        observation, reward, ended, truncated, info = env.step(1)
        assert np.isfinite(reward) and info["nav_paise"] > 0
        if info["reason"] != "simulated_fill":
            rejected += 1
        assert not truncated
    assert ended and rejected > 0
    with transaction(env.db) as session:
        assert session.get(Account, "rl-research").cash_paise >= 0
        holding = session.get(Holding, ("rl-research", ISIN))
        assert holding and holding.quantity > 0
    with pytest.raises(RuntimeError, match="Reset"):
        env.step(0)
    env.close()


def test_after_market_pipeline_success_and_repeatability(db):
    from investment_engine.models import Decision, Feature
    from investment_engine.operations import daily_research

    days = seed_backtest(db)
    at = timestamp(days[-1], 15, 35)
    first = daily_research(db, "paper", at)
    second = daily_research(db, "paper", at)
    assert first["status"] == second["status"] == "screened"
    assert first["orders_executed"] == 0
    assert first["candidates"][0]["status"] == "research_only"
    with transaction(db) as session:
        assert len(session.scalars(select(Feature)).all()) == 1
        assert len(session.scalars(select(Decision)).all()) == 1
        assert reconcile(session, "paper")["cash_paise"] == 10000000
    from investment_engine.data import DataUnavailable

    with pytest.raises(DataUnavailable, match="finalization"):
        daily_research(db, "paper", timestamp(days[-1], 15))
