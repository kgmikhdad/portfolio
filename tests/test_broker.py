from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import pytest
from conftest import ISIN, timestamp
from sqlalchemy import select

from investment_engine.broker import (
    Costs,
    LiveBroker,
    Proposal,
    Quote,
    RiskRejected,
    execute,
    initialize,
    reconcile,
)
from investment_engine.db import transaction
from investment_engine.models import Account, Bar, Holding, LedgerEntry, Membership, Order
from investment_engine.settings import Settings


def trade(market, quantity=50):
    signal, at = market
    proposal = Proposal("order-1", "test", ISIN, "buy", quantity, signal, at, "synthetic-test")
    quotes = {ISIN: Quote(ISIN, 10000, at, at, "synthetic-test")}
    return proposal, quotes


def config():
    return Settings(emergency_stop=False)


def test_atomic_persistence_and_idempotency(db, market):
    proposal, quotes = trade(market)
    with transaction(db) as session:
        first = execute(session, proposal, quotes, config())
        price, fees = first.price_paise, first.fees_paise
    with transaction(db) as session:
        duplicate = execute(session, proposal, quotes, config())
        assert duplicate.id == proposal.id
        status = reconcile(session, "test")
        assert status == {
            "cash_paise": 10000000 - 50 * price - fees,
            "orders": 1,
            "positions": 1,
            "reserved_cash_paise": 0,
        }
        holding = session.get(Holding, ("test", ISIN))
        assert holding.quantity == 50
        assert holding.cost_paise == 50 * price + fees
        with pytest.raises(RiskRejected, match="Idempotency"):
            execute(session, replace(proposal, quantity=49), quotes, config())


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"quantity": -1}, "quantity"),
        ({"quantity": 0}, "quantity"),
        ({"quantity": 100}, "allocation"),
        ({"side": "sell"}, "Short"),
        ({"signal_at": timestamp("2026-11-11", 9)}, "later trading"),
        ({"execute_at": timestamp("2026-11-11", 16)}, "outside"),
    ],
)
def test_rejected_orders_leave_no_postings(db, market, change, reason):
    proposal, quotes = trade(market)
    if "execute_at" in change:
        quotes = {
            ISIN: replace(
                quotes[ISIN], published_at=change["execute_at"], received_at=change["execute_at"]
            )
        }
    with transaction(db) as session:
        with pytest.raises(RiskRejected, match=reason):
            execute(session, replace(proposal, **change), quotes, config())
        assert reconcile(session, "test")["cash_paise"] == 10000000
        assert not session.scalars(select(Order)).all()


@pytest.mark.parametrize("condition", ["missing", "stale", "future", "membership", "stop", "cash"])
def test_required_evidence_and_stops(db, market, condition):
    proposal, quotes = trade(market)
    with transaction(db) as session:
        if condition == "missing":
            quotes = {}
        elif condition == "stale":
            quotes[ISIN] = replace(quotes[ISIN], published_at=proposal.execute_at - 901)
        elif condition == "future":
            quotes[ISIN] = replace(quotes[ISIN], received_at=proposal.execute_at + 1)
        elif condition == "membership":
            session.scalar(select(Membership)).verified = False
        elif condition == "stop":
            session.get(Account, "test").stopped = True
        elif condition == "cash":
            session.get(Account, "test").cash_paise = 1
        session.flush()
        with pytest.raises(RiskRejected):
            execute(session, proposal, quotes, config())
        assert not session.scalars(select(Order)).all()


def test_signal_data_future_and_liquidity(db, market):
    proposal, quotes = trade(market)
    with transaction(db) as session:
        bar = session.scalar(select(Bar))
        bar.received_at = proposal.signal_at + 1
        session.flush()
        with pytest.raises(RiskRejected, match="signal data"):
            execute(session, proposal, quotes, config())
        bar.received_at = proposal.signal_at - 1
        bar.volume = 100
        session.flush()
        with pytest.raises(RiskRejected, match="turnover"):
            execute(session, proposal, quotes, config())


def test_sell_and_realized_cost_basis(db, market):
    proposal, quotes = trade(market)
    with transaction(db) as session:
        buy = execute(session, proposal, quotes, config())
        basis = buy.quantity * buy.price_paise + buy.fees_paise
    at = timestamp("2026-11-12", 9, 15)
    from investment_engine.models import MarketSession

    with transaction(db) as session:
        session.add(
            MarketSession(
                day="2026-11-12",
                opens_at=at,
                closes_at=at + 20000,
                source="synthetic-test",
                verified=True,
            )
        )
        session.flush()
        quote = Quote(ISIN, 11000, at, at, "synthetic-test")
        sale = execute(
            session,
            replace(
                proposal,
                id="sell",
                side="sell",
                quantity=50,
                signal_at=at - 3600 * 18,
                execute_at=at,
            ),
            {ISIN: quote},
            config(),
        )
        assert sale.realized_paise == sale.quantity * sale.price_paise - sale.fees_paise - basis
        assert session.get(Holding, ("test", ISIN)).quantity == 0
        assert reconcile(session, "test")["cash_paise"] == 10000000 + sale.realized_paise


def test_intraday_sell_blocked(db, market):
    proposal, quotes = trade(market)
    with transaction(db) as session:
        execute(session, proposal, quotes, config())
        with pytest.raises(RiskRejected, match="Intraday"):
            execute(session, replace(proposal, id="sell", side="sell"), quotes, config())


def test_concurrent_duplicate_order(db, market):
    proposal, quotes = trade(market)

    def worker(_):
        with transaction(db) as session:
            return execute(session, proposal, quotes, config()).id

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert list(workers.map(worker, range(4))) == [proposal.id] * 4
    with transaction(db) as session:
        assert reconcile(session, "test")["orders"] == 1


def test_rollback_and_initialization_repeatability(db, market):
    proposal, quotes = trade(market)
    with pytest.raises(RuntimeError, match="simulate"):
        with transaction(db) as session:
            execute(session, proposal, quotes, config())
            raise RuntimeError("simulate downstream failure")
    with transaction(db) as session:
        initialize(session, "test", proposal.signal_at)
        assert reconcile(session, "test")["cash_paise"] == 10000000
        assert len(session.scalars(select(LedgerEntry)).all()) == 1


def test_live_execution_and_unsafe_settings_disabled():
    with pytest.raises(PermissionError):
        LiveBroker().place_order()
    with pytest.raises(ValueError):
        Settings(mode="live")
    with pytest.raises(ValueError):
        Settings(max_stock_weight=Decimal("1"))
    assert Costs().fees("sell", 100000) > Costs().fees("buy", 100000)


def test_fresh_valuation_and_pnl(db, market):
    from investment_engine.broker import mark_to_market

    proposal, quotes = trade(market)
    with transaction(db) as session:
        order = execute(session, proposal, quotes, config())
        mark = replace(quotes[ISIN], price_paise=11000)
        valuation = mark_to_market(session, "test", {ISIN: mark}, proposal.execute_at)
        assert (
            valuation["nav_paise"]
            == 10000000 - 50 * order.price_paise - order.fees_paise + 50 * 11000
        )
        assert (
            valuation["unrealized_pnl_paise"]
            == 50 * 11000 - 50 * order.price_paise - order.fees_paise
        )
        assert mark_to_market(session, "test", {ISIN: mark}, proposal.execute_at) == valuation
        with pytest.raises(RiskRejected, match="Fresh"):
            mark_to_market(session, "test", {}, proposal.execute_at + 1)


def test_cost_configuration_cannot_subsidize_trades():
    with pytest.raises(ValueError):
        Costs(buy_rate=Decimal("-0.1"))
    with pytest.raises(ValueError):
        Costs(slippage_bps=-10)
