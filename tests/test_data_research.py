from dataclasses import replace
from datetime import date

import numpy as np
import pytest
from conftest import ISIN
from sqlalchemy import select

from investment_engine.data import (
    DataUnavailable,
    JsonTransport,
    PriceBar,
    YahooResearchProvider,
    persist_bars,
    point_in_time_bars,
)
from investment_engine.db import transaction
from investment_engine.events import EventAnalysis, accept_analysis, classify
from investment_engine.features import ratio, technical, total_return_prices
from investment_engine.models import Job
from investment_engine.operations import daily_research, export_parquet
from investment_engine.research import (
    ContextualBandit,
    PromotionEvidence,
    can_promote,
    purged_walk_forward,
    train_ranking_model,
)


def test_point_in_time_revisions_and_idempotent_ingestion(db, market):
    signal, _ = market
    row = PriceBar(
        isin=ISIN,
        day="2026-11-10",
        source="synthetic-test",
        open_paise=10000,
        high_paise=20000,
        low_paise=9000,
        close_paise=15000,
        volume=1000000,
        published_at=signal - 300,
        received_at=signal + 100,
    )
    with transaction(db) as session:
        assert persist_bars(session, [row]) == 1
        assert persist_bars(session, [row.model_copy(update={"received_at": signal + 200})]) == 0
        assert point_in_time_bars(session, ISIN, signal)[-1].close_paise == 10000
        assert point_in_time_bars(session, ISIN, signal + 100)[-1].close_paise == 15000


def test_invalid_prices_and_missing_features():
    with pytest.raises(ValueError):
        technical([0, 1])
    assert technical([100])["momentum20"] is None
    assert ratio(2, 0) is None
    assert technical([100] * 21)["rsi14"] == 50
    prices = total_return_prices([100, 50, 49], {1: 2}, {2: 1})
    assert np.allclose(prices, [100, 100, 100])


def test_provider_does_not_request_without_permission(tmp_path):
    provider = YahooResearchProvider(JsonTransport(tmp_path))
    with pytest.raises(DataUnavailable, match="permission"):
        provider.history(ISIN, "TEST.NS", date(2026, 1, 1), date(2026, 2, 1))
    assert not list(tmp_path.iterdir())


def test_failed_daily_job_is_durable_and_no_trade(db):
    with pytest.raises(DataUnavailable, match="empty"):
        daily_research(db, "paper", 1000000)
    with transaction(db) as session:
        job = session.scalar(select(Job))
        assert job.status == "blocked" and job.finished_at
        from investment_engine.broker import reconcile

        assert reconcile(session, "paper")["cash_paise"] == 10000000
        assert reconcile(session, "paper")["orders"] == 0


def test_archive_provenance(db, market, tmp_path):
    import json

    import pyarrow.parquet as pq

    destination = tmp_path / "prices.parquet"
    assert export_parquet(db, destination) == 1
    table = pq.read_table(destination)
    assert "received_at" in table.column_names and "content_hash" in table.column_names
    assert json.loads(destination.with_suffix(".manifest.json").read_text())["rows"] == 1


def test_purging_overlapping_labels_and_reproducibility():
    times = np.arange(100, dtype=np.int64)
    ends = times + 20
    folds = purged_walk_forward(times, ends, [60, 80], 10, embargo=5)
    for train, valid in folds:
        assert np.max(ends[train]) < np.min(times[valid]) - 5
    x = np.column_stack([times / 100, np.sin(times)])
    y = times / 1000
    a = train_ranking_model(x, y, *folds[0])
    b = train_ranking_model(x, y, *folds[0])
    assert a == b and a["status"] == "experimental"
    with pytest.raises(ValueError):
        train_ranking_model(x, y, folds[0][0], folds[0][0])


def test_model_promotion_requires_evidence():
    good = PromotionEvidence(500, 4, 0.01, 0.1, 0.2, True, 90, "independent-review")
    assert can_promote(good)
    for field, value in [
        ("out_of_sample_observations", 20),
        ("leakage_checks_passed", False),
        ("independent_approval_id", None),
        ("lower_excess_return_bound", -0.1),
        ("prospective_paper_days", 0),
        ("maximum_drawdown", float("nan")),
    ]:
        assert not can_promote(replace(good, **{field: value}))


def test_bandit_cash_and_update():
    bandit = ContextualBandit(3, 2, alpha=0)
    context = np.array([1.0, 0.0])
    assert bandit.choose(context) == 0
    bandit.update(1, context, 0.2)
    assert bandit.choose(context) == 1
    bandit.update(1, context, -1)
    assert bandit.choose(context) == 0


def test_event_triage_and_failed_analysis_cannot_corrupt_ledger(db, market):
    from investment_engine.broker import reconcile

    assert classify("Board approves interim dividend") == ("dividend", False)
    assert classify("Merger with contingent consideration") == ("merger", True)
    before = None
    with transaction(db) as session:
        before = reconcile(session, "test")
        payload = dict(
            schema_version="1",
            event_id="unknown",
            isin=ISIN,
            source_url="https://www.nseindia.com/test",
            published_at=1,
            assessed_at=2,
            classification="merger",
            facts=[],
            financial_materiality="unknown",
            economic_channels=[],
            positive_interpretations=[],
            negative_interpretations=[],
            expectation_uncertainty="high",
            unresolved_questions=["terms"],
            confidence=0.1,
            analysis_status="needs_evidence",
        )
        with pytest.raises(ValueError):
            accept_analysis(session, EventAnalysis(**payload))
        assert reconcile(session, "test") == before
