import json
import time
from datetime import date
from pathlib import Path

import typer
from sqlalchemy import select, text

from investment_engine.broker import initialize
from investment_engine.data import (
    DataUnavailable,
    JsonTransport,
    YahooResearchProvider,
    persist_actions,
    persist_bars,
)
from investment_engine.db import engine, transaction
from investment_engine.models import Security
from investment_engine.operations import daily_research, export_parquet, portfolio_report
from investment_engine.settings import settings

app = typer.Typer(no_args_is_help=True, help="INR research and paper ledger; live trading disabled")


def output(value: object) -> None:
    typer.echo(json.dumps(value, default=str, sort_keys=True))


@app.command()
def doctor() -> None:
    """Check migrated database and paper-only configuration without exposing credentials."""
    cfg = settings()
    db = engine(cfg.database_url.get_secret_value())
    with db.connect() as connection:
        revision: str = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    output(
        {
            "database": "connected",
            "revision": revision,
            "mode": cfg.mode,
            "emergency_stop": cfg.emergency_stop,
            "data_permission": cfg.market_data_permitted,
        }
    )


@app.command()
def init(account: str = "paper") -> None:
    db = engine(settings().database_url.get_secret_value())
    at = int(time.time())
    with transaction(db) as session:
        initialize(session, account, at)
    output(portfolio_report(db, account, at))


@app.command()
def report(account: str = "paper") -> None:
    output(
        portfolio_report(
            engine(settings().database_url.get_secret_value()), account, int(time.time())
        )
    )


@app.command()
def ingest(isin: str, start: str, end: str) -> None:
    """Fetch a reconciled NSE identifier after usage permission is established."""
    cfg = settings()
    db = engine(cfg.database_url.get_secret_value())
    with transaction(db) as session:
        security = session.get(Security, isin)
        if security is None:
            raise typer.BadParameter("Load a verified security master before ingestion")
        # Identifier reconciliation must be explicit; never append suffixes to exchange symbols.
        from investment_engine.models import Identifier

        identifiers = session.scalars(
            select(Identifier).where(
                Identifier.isin == isin,
                Identifier.provider == "yahoo",
                Identifier.valid_from <= int(time.time()),
                Identifier.valid_to.is_(None),
            )
        ).all()
        if len(identifiers) != 1:
            raise typer.BadParameter("Exactly one reconciled current Yahoo identifier required")
        symbol = identifiers[0].symbol
    try:
        provider = YahooResearchProvider(
            JsonTransport(Path("var/cache/yahoo"), daily_quota=100),
            permitted=cfg.market_data_permitted,
        )
        bars = provider.history(isin, symbol, date.fromisoformat(start), date.fromisoformat(end))
        with transaction(db) as session:
            count = persist_bars(session, bars)
            persist_actions(session, provider.actions)
        output({"status": "ingested", "new_rows": count, "provider": "yahoo-research"})
    except DataUnavailable as error:
        output({"status": "blocked", "reason": str(error)})
        raise typer.Exit(3) from error


@app.command()
def daily(account: str = "paper", as_of: int | None = None) -> None:
    try:
        at = as_of if as_of is not None else int(time.time())
        if at > int(time.time()):
            raise typer.BadParameter("Future research time prohibited")
        result = daily_research(engine(settings().database_url.get_secret_value()), account, at)
        output(result)
        if result["status"] == "partial":
            raise typer.Exit(3)
    except DataUnavailable as error:
        output({"status": "blocked", "reason": str(error), "orders_executed": 0})
        raise typer.Exit(3) from error


@app.command()
def archive(destination: Path) -> None:
    count = export_parquet(engine(settings().database_url.get_secret_value()), destination)
    output({"rows": count, "destination": str(destination)})


@app.command()
def reference(manifest: Path, source_document: Path, reviewed: bool = False) -> None:
    """Import an operator-reviewed official membership snapshot with an explicit expiry."""
    from investment_engine.reference import ReferenceManifest, import_reference

    data = ReferenceManifest.model_validate_json(manifest.read_text())
    with transaction(engine(settings().database_url.get_secret_value())) as session:
        count = import_reference(session, data, source_document, operator_reviewed=reviewed)
    output(
        {
            "status": "reference_imported",
            "new_memberships": count,
            "constituents": len(data.constituents),
            "document_sha256": data.document_sha256,
        }
    )


@app.command()
def health(account: str = "paper") -> None:
    from investment_engine.monitoring import health as check_health

    result = check_health(
        engine(settings().database_url.get_secret_value()), account, int(time.time())
    )
    output(result)
    if result["status"] != "healthy":
        raise typer.Exit(3)
