from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select

from investment_engine.broker import initialize, reconcile
from investment_engine.dashboard_data import dashboard_data
from investment_engine.data import DataUnavailable, PriceBar
from investment_engine.db import transaction
from investment_engine.market_pipeline import frame_to_records, ingest_market, load_registry
from investment_engine.models import Bar, Feature, Job, Order


def test_registry_ids_and_special_series_are_explicit():
    config = load_registry()
    assert len(config["securities"]) == 203
    assert config["universe_verified"] is False
    assert next(r for r in config["securities"] if r["symbol"] == "HFCL")["series"] == "BE"


def test_yahoo_frame_keeps_adjustment_and_does_not_credit_dividends():
    now = int(datetime.now(UTC).timestamp())
    dates = pd.date_range(
        datetime.now(UTC).date() - timedelta(days=3), periods=3, tz="Asia/Kolkata"
    )
    frame = pd.DataFrame(
        {
            "Open": [50] * 3,
            "High": [51] * 3,
            "Low": [49] * 3,
            "Close": [50] * 3,
            "Adj Close": [49, 49, 50],
            "Volume": [1000000] * 3,
            "Dividends": [0, 0, 1],
            "Stock Splits": [0, 2, 0],
        },
        index=dates,
    )
    bars, actions = frame_to_records(frame, "INE009A01021", now)
    assert len(bars) == 3 and len(actions) == 2
    assert bars[0].close_paise == bars[1].close_paise  # already split-adjusted Yahoo basis
    assert bars[0].adjusted_close_paise == 4900
    assert {a["kind"] for a in actions} == {"dividend", "split"}
    frame.loc[dates[1], "Volume"] = -1
    with pytest.raises(DataUnavailable, match="volume"):
        frame_to_records(frame, "INE009A01021", now)


@pytest.fixture()
def ingestion_inputs(db, monkeypatch):
    now = int(datetime.now(UTC).timestamp())
    config = load_registry()
    config["securities"] = config["securities"][:3]
    with transaction(db) as session:
        initialize(session, "paper", now)
    monkeypatch.setattr("investment_engine.market_pipeline.load_registry", lambda: config)
    monkeypatch.setattr(
        "investment_engine.market_pipeline.reconcile_registry",
        lambda _: {"status": "synthetic-test-registry"},
    )
    monkeypatch.setattr("investment_engine.market_pipeline.time.sleep", lambda _: None)
    return config, now


def test_ingestion_and_dashboard_read_real_backend_tables_idempotently(
    db, ingestion_inputs, monkeypatch
):
    config, now = ingestion_inputs

    def download(symbol, isin, last_day, backfill):
        rows = []
        for i in range(30):
            day = datetime.now(UTC).date() - timedelta(days=30 - i)
            rows.append(
                PriceBar(
                    isin=isin,
                    day=day,
                    source="yfinance-research",
                    open_paise=10000,
                    high_paise=11000,
                    low_paise=9000,
                    close_paise=10000,
                    adjusted_close_paise=10000,
                    volume=1000000,
                    published_at=int(
                        datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()
                    ),
                    received_at=now,
                )
            )
        return rows, []

    monkeypatch.setattr("investment_engine.market_pipeline.download_history", download)
    first = ingest_market(db)
    second = ingest_market(db)
    assert first["status"] == second["status"] == "ingested"
    assert first["succeeded"] == 3 and first["new_bars"] == 90
    assert second["new_bars"] == 0
    result = dashboard_data(db)
    assert result["source"] == "backend_database" and result["bar_count"] == 90
    assert len(result["research"]) == 3
    assert all(r["trade_approved"] is False for r in result["research"])
    assert result["portfolio"]["cash_paise"] == 10000000
    assert result["portfolio"]["executions"] == []
    with transaction(db) as session:
        assert session.scalar(select(func.count()).select_from(Feature)) == 3
        assert session.scalar(select(func.count()).select_from(Order)) == 0
        assert reconcile(session, "paper")["cash_paise"] == 10000000


def test_provider_failure_is_recorded_as_blocked(db, ingestion_inputs, monkeypatch):
    def fail(*args, **kwargs):
        raise DataUnavailable("Synthetic provider failure")

    monkeypatch.setattr("investment_engine.market_pipeline.download_history", fail)
    result = ingest_market(db)
    assert result["status"] == "blocked" and result["failed"] == 3
    with transaction(db) as session:
        assert session.get(Job, result["job_id"]).status == "blocked"
        assert session.scalar(select(func.count()).select_from(Bar)) == 0
        assert reconcile(session, "paper")["orders"] == 0
