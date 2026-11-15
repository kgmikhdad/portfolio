from datetime import date

import numpy as np
import pytest

from investment_engine.data import DataUnavailable
from investment_engine.model_training import feature_vector, fit_candidate


def synthetic_series():
    rng = np.random.default_rng(42)
    return [
        {
            "isin": f"SYNTHETIC-{i}",
            "prices": (100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 1200)))).tolist(),
            "days": list(range(date(2020, 1, 1).toordinal(), date(2020, 1, 1).toordinal() + 1200)),
        }
        for i in range(3)
    ]


@pytest.mark.parametrize("horizon", [20, 60, 120, 250])
def test_candidates_are_purged_reproducible_and_unapproved(horizon):
    a = fit_candidate(synthetic_series(), horizon)
    b = fit_candidate(synthetic_series(), horizon)
    assert a == b
    assert a["metrics"]["purging_verified"]
    assert a["metrics"]["promotion_approved"] is False
    assert a["metrics"]["survivorship_bias_unresolved"] is True
    assert len(a["predictions"]) == 3
    assert all(np.isfinite(p["estimate"]) for p in a["predictions"])


def test_final_test_changes_cannot_change_training_scaler_or_coefficients():
    series = synthetic_series()
    baseline = fit_candidate(series, 20)
    for item in series:
        item["prices"][-100:] = [p * 3 for p in item["prices"][-100:]]
    changed = fit_candidate(series, 20)
    assert baseline["parameters"] == changed["parameters"]
    assert baseline["metrics"]["untouched_test_mse"] != changed["metrics"]["untouched_test_mse"]


def test_insufficient_or_invalid_history_blocks_training():
    with pytest.raises(DataUnavailable):
        fit_candidate([], 20)
    with pytest.raises(ValueError):
        feature_vector([1, 2], 1)


def test_fixed_model_inference_is_idempotent_and_never_changes_cash(db):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from investment_engine.broker import initialize, reconcile
    from investment_engine.data import PriceBar, persist_bars
    from investment_engine.db import transaction
    from investment_engine.model_training import refresh_predictions
    from investment_engine.models import Decision, Experiment, Prediction, Security

    now = int(datetime.now(UTC).timestamp())
    with transaction(db) as session:
        initialize(session, "paper", now)
        session.add(Security(isin="INE009A01021", symbol="SYNTHETIC", sector="Test"))
        session.flush()
        bars = []
        for index in range(300):
            day = datetime.now(UTC).date() - timedelta(days=300 - index)
            bars.append(
                PriceBar(
                    isin="INE009A01021",
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
        persist_bars(session, bars)
        session.add(
            Experiment(
                id="synthetic-model",
                model_kind="ridge-price-only-20",
                dataset_hash="test",
                code_version="test",
                seed=42,
                created_at=now,
                status="experimental",
                metrics={},
                parameters={
                    "horizon": 20,
                    "scaler_mean": [0] * 6,
                    "scaler_scale": [1] * 6,
                    "coefficients": [0] * 6,
                    "intercept": 0.1,
                    "residual_scale": 0.02,
                },
            )
        )
    assert refresh_predictions(db)["forecasts_updated"] == 1
    assert refresh_predictions(db)["forecasts_updated"] == 0
    with transaction(db) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 1
        assert session.scalar(select(func.count()).select_from(Decision)) == 1
        assert reconcile(session, "paper")["cash_paise"] == 10000000
        assert reconcile(session, "paper")["orders"] == 0
