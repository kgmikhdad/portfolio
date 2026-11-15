"""Atomic whole-share delivery accounting. All amounts are integer paise."""

from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investment_engine.data import IST, digest, point_in_time_bars
from investment_engine.models import (
    Account,
    ActionPosting,
    Holding,
    LedgerEntry,
    MarketSession,
    Membership,
    Order,
    Security,
)
from investment_engine.settings import Settings


class RiskRejected(ValueError):
    pass


@dataclass(frozen=True)
class Costs:
    """Conservative research assumptions, not a verified statutory/broker fee schedule.

    Charges include an aggregate delivery-rate allowance plus sell-side depository cost.
    A deployment must replace these with a reviewed effective-dated cost schedule.
    """

    version: str = "research-conservative-v1"
    buy_rate: Decimal = Decimal("0.0015")
    sell_rate: Decimal = Decimal("0.0015")
    sell_dp_paise: int = 2000
    slippage_bps: int = 10

    def __post_init__(self) -> None:
        if not (
            0 <= self.buy_rate <= Decimal("0.05")
            and 0 <= self.sell_rate <= Decimal("0.05")
            and 0 <= self.slippage_bps <= 1000
            and self.sell_dp_paise >= 0
        ):
            raise ValueError("Invalid nonnegative transaction cost assumptions")

    def fees(self, side: str, notional: int) -> int:
        rate = self.buy_rate if side == "buy" else self.sell_rate
        return int((notional * rate).quantize(Decimal("1"), rounding=ROUND_CEILING)) + (
            self.sell_dp_paise if side == "sell" else 0
        )

    def execution_price(self, side: str, raw_price: int) -> int:
        sign = 1 if side == "buy" else -1
        return int(
            (Decimal(raw_price) * (1 + Decimal(sign * self.slippage_bps) / 10000)).quantize(
                Decimal("1"), rounding=ROUND_CEILING
            )
        )


@dataclass(frozen=True)
class Quote:
    isin: str
    price_paise: int
    published_at: int
    received_at: int
    source: str


@dataclass(frozen=True)
class Proposal:
    id: str
    account_id: str
    isin: str
    side: Literal["buy", "sell"]
    quantity: int
    signal_at: int
    execute_at: int
    reason: str


def initialize(
    session: Session, account_id: str, at: int, capital_paise: int = 10000000
) -> Account:
    if capital_paise != 10000000:
        raise ValueError("Initial release requires INR 100000")
    account = session.get(Account, account_id)
    if account is None:
        account = Account(id=account_id, initial_paise=capital_paise, cash_paise=capital_paise)
        session.add(account)
        session.flush()
        session.add(
            LedgerEntry(
                id=f"{account_id}:initial",
                account_id=account_id,
                at=at,
                amount_paise=capital_paise,
                kind="initial",
            )
        )
        session.flush()
    return account


def reconcile(session: Session, account_id: str) -> dict[str, int]:
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError("Unknown account")
    ledger_cash = (
        session.scalar(
            select(func.sum(LedgerEntry.amount_paise)).where(LedgerEntry.account_id == account_id)
        )
        or 0
    )
    if ledger_cash != account.cash_paise:
        raise RuntimeError("Cash/ledger reconciliation failed")
    holdings = session.scalars(select(Holding).where(Holding.account_id == account_id)).all()
    orders = session.scalars(select(Order).where(Order.account_id == account_id)).all()
    expected: dict[str, int] = {}
    for order in orders:
        expected[order.isin] = expected.get(order.isin, 0) + (
            order.quantity if order.side == "buy" else -order.quantity
        )
    for posting in session.scalars(
        select(ActionPosting).where(ActionPosting.account_id == account_id)
    ):
        expected[posting.isin] = expected.get(posting.isin, 0) + posting.share_delta
    for holding in holdings:
        if holding.quantity != expected.pop(holding.isin, 0):
            raise RuntimeError("Holdings/orders reconciliation failed")
    if any(expected.values()):
        raise RuntimeError("Missing holding")
    return {
        "cash_paise": account.cash_paise,
        "orders": len(orders),
        "positions": sum(h.quantity > 0 for h in holdings),
        "reserved_cash_paise": 0,
    }


def execute(
    session: Session,
    proposal: Proposal,
    quotes: dict[str, Quote],
    config: Settings,
    costs: Costs = Costs(),
) -> Order:
    # Account row lock serializes valuation, risk, idempotency, and all postings.
    account = session.scalar(
        select(Account).where(Account.id == proposal.account_id).with_for_update()
    )
    if account is None:
        raise RiskRejected("Unknown account")
    fingerprint = digest({"proposal": asdict(proposal), "costs": asdict(costs)})
    existing = session.get(Order, proposal.id)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise RiskRejected("Idempotency key reused with different inputs")
        return existing
    if config.emergency_stop or account.stopped:
        raise RiskRejected("Emergency stop active")
    if proposal.side not in ("buy", "sell") or type(proposal.quantity) is not int:
        raise RiskRejected("Invalid order type or quantity")
    if proposal.quantity <= 0 or proposal.execute_at <= proposal.signal_at:
        raise RiskRejected("Invalid quantity or time ordering")
    security = session.get(Security, proposal.isin)
    if security is None or security.exchange != "NSE" or security.instrument != "equity":
        raise RiskRejected("Only identified NSE cash equities are supported")
    from datetime import datetime

    execution_day = datetime.fromtimestamp(proposal.execute_at, IST).date().isoformat()
    signal_day = datetime.fromtimestamp(proposal.signal_at, IST).date().isoformat()
    market = session.get(MarketSession, execution_day)
    if market is None or not market.verified:
        raise RiskRejected("No verified exchange session")
    if not market.opens_at <= proposal.execute_at <= market.closes_at:
        raise RiskRejected("Execution outside exchange session")
    if signal_day >= execution_day:
        raise RiskRejected("Signals execute on a later trading session")
    holdings = session.scalars(
        select(Holding).where(Holding.account_id == account.id, Holding.quantity > 0)
    ).all()
    required = {h.isin for h in holdings} | {proposal.isin}
    for isin in required:
        quote = quotes.get(isin)
        if (
            quote is None
            or quote.isin != isin
            or type(quote.price_paise) is not int
            or quote.price_paise <= 0
        ):
            raise RiskRejected("Missing valid portfolio mark")
        if not quote.published_at <= quote.received_at <= proposal.execute_at:
            raise RiskRejected("Price not available at execution")
        if proposal.execute_at - quote.published_at > 900:
            raise RiskRejected("Stale execution quote")
    quote = quotes[proposal.isin]
    price = costs.execution_price(proposal.side, quote.price_paise)
    notional = proposal.quantity * price
    fees = costs.fees(proposal.side, notional)
    holding = session.get(Holding, (account.id, proposal.isin))
    realized = 0
    if proposal.side == "buy":
        membership = session.scalar(
            select(Membership).where(
                Membership.isin == proposal.isin,
                Membership.verified.is_(True),
                Membership.index_name == "Nifty500 Shariah",
                Membership.valid_from <= proposal.execute_at,
                Membership.valid_to > proposal.execute_at,
                Membership.published_at <= proposal.signal_at,
                Membership.received_at <= proposal.signal_at,
            )
        )
        if membership is None:
            raise RiskRejected("No verified point-in-time Shariah membership")
        bars = point_in_time_bars(session, proposal.isin, proposal.signal_at)
        if not bars or proposal.signal_at - bars[-1].published_at > (
            config.max_price_age_hours * 3600
        ):
            raise RiskRejected("Missing or stale signal data")
        prior = bars[-1]
        if prior.close_paise * prior.volume < config.minimum_daily_turnover * 100:
            raise RiskRejected("Insufficient daily turnover")
        if proposal.quantity > Decimal(prior.volume) * config.max_volume_fraction:
            raise RiskRejected("Participation limit exceeded")
        if notional + fees > account.cash_paise:
            raise RiskRejected("Insufficient available cash")
        nav = account.cash_paise + sum(h.quantity * quotes[h.isin].price_paise for h in holdings)
        post_nav = nav - fees - proposal.quantity * (price - quote.price_paise)
        stock_value = ((holding.quantity if holding else 0) + proposal.quantity) * price
        sector_value = notional
        for h in holdings:
            held_security = session.get(Security, h.isin)
            if held_security is None:
                raise RiskRejected("Missing sector classification")
            if held_security.sector == security.sector:
                sector_value += h.quantity * quotes[h.isin].price_paise
        if stock_value > Decimal(post_nav) * config.max_stock_weight:
            raise RiskRejected("Stock allocation limit exceeded")
        if sector_value > Decimal(post_nav) * config.max_sector_weight:
            raise RiskRejected("Sector allocation limit exceeded")
        if holding is None:
            holding = Holding(account_id=account.id, isin=proposal.isin, quantity=0, cost_paise=0)
            session.add(holding)
        holding.quantity += proposal.quantity
        holding.cost_paise += notional + fees
        cash_change = -notional - fees
    else:
        if holding is None or proposal.quantity > holding.quantity:
            raise RiskRejected("Short selling prohibited")
        latest_buy = session.scalar(
            select(func.max(Order.executed_at)).where(
                Order.account_id == account.id, Order.isin == proposal.isin, Order.side == "buy"
            )
        )
        if (
            latest_buy
            and datetime.fromtimestamp(latest_buy, IST).date().isoformat() >= execution_day
        ):
            raise RiskRejected("Intraday round trips prohibited")
        if notional <= fees:
            raise RiskRejected("Sale proceeds do not cover costs")
        released_basis = (
            holding.cost_paise
            if proposal.quantity == holding.quantity
            else holding.cost_paise * proposal.quantity // holding.quantity
        )
        holding.quantity -= proposal.quantity
        holding.cost_paise -= released_basis
        cash_change = notional - fees
        realized = cash_change - released_basis
    account.cash_paise += cash_change
    order = Order(
        id=proposal.id,
        account_id=account.id,
        isin=proposal.isin,
        fingerprint=fingerprint,
        side=proposal.side,
        quantity=proposal.quantity,
        price_paise=price,
        fees_paise=fees,
        realized_paise=realized,
        signal_at=proposal.signal_at,
        executed_at=proposal.execute_at,
        reason=proposal.reason,
    )
    session.add(order)
    session.flush()
    session.add(
        LedgerEntry(
            id=f"order:{order.id}",
            account_id=account.id,
            order_id=order.id,
            at=proposal.execute_at,
            amount_paise=cash_change,
            kind=proposal.side,
        )
    )
    session.flush()
    reconcile(session, account.id)
    return order


class LiveBroker:
    def place_order(self, *_: object, **__: object) -> None:
        raise PermissionError("Live execution is unimplemented and disabled")


def mark_to_market(
    session: Session, account_id: str, quotes: dict[str, Quote], at: int
) -> dict[str, int]:
    from investment_engine.models import Valuation

    account = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if account is None:
        raise ValueError("Unknown account")
    holdings = session.scalars(
        select(Holding).where(Holding.account_id == account_id, Holding.quantity > 0)
    ).all()
    marks = {}
    market_value = basis = 0
    for holding in holdings:
        quote = quotes.get(holding.isin)
        if (
            quote is None
            or quote.price_paise <= 0
            or not (quote.published_at <= quote.received_at <= at)
            or at - quote.published_at > 900
        ):
            raise RiskRejected("Fresh available marks required for valuation")
        marks[holding.isin] = {
            "price_paise": quote.price_paise,
            "source": quote.source,
            "published_at": quote.published_at,
            "received_at": quote.received_at,
        }
        market_value += holding.quantity * quote.price_paise
        basis += holding.cost_paise
    nav = account.cash_paise + market_value
    existing = session.get(Valuation, (account_id, at))
    if existing:
        if existing.nav_paise != nav or existing.marks != marks:
            raise ValueError("Valuation timestamp already has a different snapshot")
    else:
        session.add(
            Valuation(
                account_id=account_id,
                at=at,
                nav_paise=nav,
                cash_paise=account.cash_paise,
                marks=marks,
            )
        )
        session.flush()
    return {
        "nav_paise": nav,
        "cash_paise": account.cash_paise,
        "market_value_paise": market_value,
        "unrealized_pnl_paise": market_value - basis,
    }
