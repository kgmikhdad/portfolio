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
