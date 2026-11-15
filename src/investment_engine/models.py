"""Append-only observations retain publication and receipt times as UTC epoch seconds."""

from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Security(Base):
    __tablename__ = "securities"
    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), unique=True)
    sector: Mapped[str] = mapped_column(String(80))
    exchange: Mapped[str] = mapped_column(default="NSE")
    instrument: Mapped[str] = mapped_column(default="equity")
    __table_args__ = (CheckConstraint("length(isin) = 12"),)


class Identifier(Base):
    __tablename__ = "identifiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    provider: Mapped[str]
    symbol: Mapped[str]
    valid_from: Mapped[int]
    valid_to: Mapped[int | None]
    source: Mapped[str]
    __table_args__ = (UniqueConstraint("provider", "symbol", "valid_from"),)


class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    index_name: Mapped[str] = mapped_column(default="Nifty500 Shariah")
    valid_from: Mapped[int]
    valid_to: Mapped[int]
    published_at: Mapped[int]
    received_at: Mapped[int]
    source: Mapped[str]
    document_hash: Mapped[str]
    verified: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (CheckConstraint("valid_to > valid_from"),)


class MarketSession(Base):
    __tablename__ = "market_sessions"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    opens_at: Mapped[int]
    closes_at: Mapped[int]
    source: Mapped[str]
    verified: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (CheckConstraint("closes_at > opens_at"),)


class Bar(Base):
    __tablename__ = "bars"
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    day: Mapped[str] = mapped_column(String(10))
    source: Mapped[str]
    open_paise: Mapped[int]
    high_paise: Mapped[int]
    low_paise: Mapped[int]
    close_paise: Mapped[int]
    adjusted_close_paise: Mapped[int | None]
    volume: Mapped[int]
    published_at: Mapped[int]
    received_at: Mapped[int]
    content_hash: Mapped[str]
    __table_args__ = (
        UniqueConstraint("isin", "day", "source", "content_hash"),
        CheckConstraint("low_paise > 0 AND high_paise >= low_paise"),
        CheckConstraint("open_paise >= low_paise AND open_paise <= high_paise"),
        CheckConstraint("close_paise >= low_paise AND close_paise <= high_paise"),
        CheckConstraint("volume >= 0"),
        Index("ix_bars_pit", "isin", "published_at", "received_at"),
    )


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    id: Mapped[str] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    kind: Mapped[str]
    effective_at: Mapped[int]
    published_at: Mapped[int]
    received_at: Mapped[int]
    numerator: Mapped[int | None]
    denominator: Mapped[int | None]
    cash_paise: Mapped[int | None]
    source: Mapped[str]
    __table_args__ = (CheckConstraint("kind IN ('split', 'dividend')"),)


class Observation(Base):
    """Versioned structured financial, macro, sector and flow facts; never overwrite revisions."""

    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str | None] = mapped_column(ForeignKey("securities.isin"))
    category: Mapped[str]
    name: Mapped[str]
    period: Mapped[str]
    value: Mapped[str]
    unit: Mapped[str]
    published_at: Mapped[int]
    received_at: Mapped[int]
    source: Mapped[str]
    content_hash: Mapped[str]
    __table_args__ = (UniqueConstraint("source", "content_hash"),)


class ResearchEvent(Base):
    __tablename__ = "research_events"
    id: Mapped[str] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    source_url: Mapped[str]
    published_at: Mapped[int]
    received_at: Mapped[int]
    document_hash: Mapped[str] = mapped_column(unique=True)
    classification: Mapped[str]
    needs_review: Mapped[bool]
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(default="pending")


class Feature(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    definition_version: Mapped[str]
    as_of: Mapped[int]
    values: Mapped[dict[str, Any]] = mapped_column(JSON)
    dataset_hash: Mapped[str]
    __table_args__ = (UniqueConstraint("isin", "definition_version", "as_of", "dataset_hash"),)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(primary_key=True)
    model_kind: Mapped[str]
    dataset_hash: Mapped[str]
    code_version: Mapped[str]
    seed: Mapped[int]
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[int]
    status: Mapped[str] = mapped_column(default="experimental")


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    as_of: Mapped[int]
    horizon: Mapped[int]
    estimate: Mapped[float]
    uncertainty: Mapped[float]


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(primary_key=True)
    initial_paise: Mapped[int] = mapped_column(default=10000000)
    cash_paise: Mapped[int]
    stopped: Mapped[bool] = mapped_column(default=True)
    currency: Mapped[str] = mapped_column(default="INR")
    __table_args__ = (
        CheckConstraint("cash_paise >= 0 AND initial_paise > 0"),
        CheckConstraint("currency = 'INR'"),
    )


class Holding(Base):
    __tablename__ = "holdings"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"), primary_key=True)
    quantity: Mapped[int]
    cost_paise: Mapped[int]
    __table_args__ = (CheckConstraint("quantity >= 0 AND cost_paise >= 0"),)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    isin: Mapped[str | None] = mapped_column(ForeignKey("securities.isin"))
    at: Mapped[int]
    kind: Mapped[str]
    reason: Mapped[str]
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    fingerprint: Mapped[str]
    side: Mapped[str]
    quantity: Mapped[int]
    price_paise: Mapped[int]
    fees_paise: Mapped[int]
    realized_paise: Mapped[int]
    signal_at: Mapped[int]
    executed_at: Mapped[int]
    reason: Mapped[str]
    __table_args__ = (
        CheckConstraint("quantity > 0 AND price_paise > 0 AND fees_paise >= 0"),
        CheckConstraint("side IN ('buy', 'sell')"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger"
    id: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), unique=True)
    at: Mapped[int]
    amount_paise: Mapped[int]
    kind: Mapped[str]


class Valuation(Base):
    __tablename__ = "valuations"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    at: Mapped[int] = mapped_column(primary_key=True)
    nav_paise: Mapped[int]
    cash_paise: Mapped[int]
    marks: Mapped[dict[str, Any]] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(primary_key=True)
    started_at: Mapped[int]
    finished_at: Mapped[int | None]
    status: Mapped[str]
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class BacktestRun(Base):
    __tablename__ = "backtests"
    id: Mapped[str] = mapped_column(primary_key=True)
    dataset_hash: Mapped[str]
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON)
    results: Mapped[dict[str, Any]] = mapped_column(JSON)


class ActionPosting(Base):
    __tablename__ = "action_postings"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("corporate_actions.id"), primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("securities.isin"))
    share_delta: Mapped[int]
    cash_paise: Mapped[int]
    at: Mapped[int]
