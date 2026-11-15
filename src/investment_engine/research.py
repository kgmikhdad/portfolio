"""Strict walk-forward research utilities. Nothing here is automatically promoted."""

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from investment_engine.data import digest


@dataclass(frozen=True)
class PromotionEvidence:
    out_of_sample_observations: int
    walk_forward_folds: int
    lower_excess_return_bound: float
    maximum_drawdown: float
    baseline_maximum_drawdown: float
    leakage_checks_passed: bool
    prospective_paper_days: int
    independent_approval_id: str | None


def can_promote(e: PromotionEvidence) -> bool:
    values = [e.lower_excess_return_bound, e.maximum_drawdown, e.baseline_maximum_drawdown]
    return bool(
        all(np.isfinite(values))
        and e.out_of_sample_observations >= 250
        and e.walk_forward_folds >= 3
        and e.lower_excess_return_bound > 0
        and 0 <= e.maximum_drawdown <= e.baseline_maximum_drawdown
        and e.leakage_checks_passed
        and e.prospective_paper_days >= 60
        and e.independent_approval_id
    )


def purged_walk_forward(
    times: NDArray[np.int64],
    label_ends: NDArray[np.int64],
    validation_starts: list[int],
    validation_width: int,
    embargo: int = 0,
) -> list[tuple[NDArray[np.int64], NDArray[np.int64]]]:
    if len(times) != len(label_ends) or np.any(label_ends < times) or embargo < 0:
        raise ValueError("Invalid temporal labels")
    if validation_width <= 0 or np.any(np.diff(times) < 0):
        raise ValueError("Expected sorted observations and positive validation width")
    folds = []
    for start in validation_starts:
        train = np.flatnonzero((times < start) & (label_ends < start - embargo))
        valid = np.flatnonzero((times >= start) & (times < start + validation_width))
        if len(train) == 0 or len(valid) == 0:
            raise ValueError("Empty training/validation fold")
        folds.append((train, valid))
    return folds


def train_ranking_model(
    features: NDArray[np.float64],
    targets: NDArray[np.float64],
    train: NDArray[np.int64],
    valid: NDArray[np.int64],
    seed: int = 42,
) -> dict[str, Any]:
    if np.intersect1d(train, valid).size or not train.size or not valid.size:
        raise ValueError("Disjoint nonempty splits required")
    if not np.all(np.isfinite(features)) or not np.all(np.isfinite(targets)):
        raise ValueError("Missing features block training")
    model = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    model.fit(features[train], targets[train])
    predictions = model.predict(features[valid])
    errors = predictions - targets[valid]
    return {
        "model_kind": "ridge-baseline",
        "seed": seed,
        "status": "experimental",
        "dataset_hash": digest(
            {
                "x": features.tolist(),
                "y": targets.tolist(),
                "train": train.tolist(),
                "valid": valid.tolist(),
            }
        ),
        "mse": float(np.mean(errors**2)),
        "predictions": predictions.tolist(),
        "coefficients": model[-1].coef_.tolist(),
    }


class ContextualBandit:
    """Disjoint LinUCB research baseline; arm zero explicitly represents cash.

    Rewards must be supplied only when their investment horizon has matured.
    External risk checks remain mandatory for any resulting portfolio decision.
    """

    def __init__(self, arms: int, dimensions: int, alpha: float = 0.1) -> None:
        if arms < 1 or dimensions < 1 or alpha < 0:
            raise ValueError("Invalid bandit dimensions")
        self.a = np.repeat(np.eye(dimensions)[None, :, :], arms, axis=0)
        self.b = np.zeros((arms, dimensions))
        self.alpha = alpha

    def choose(self, context: NDArray[np.float64]) -> int:
        if not np.all(np.isfinite(context)):
            raise ValueError("Finite context required")
        scores = [0.0]
        for arm in range(1, len(self.a)):
            inverse = np.linalg.inv(self.a[arm])
            scores.append(
                float(
                    (inverse @ self.b[arm]) @ context
                    + self.alpha * np.sqrt(context @ inverse @ context)
                )
            )
        return int(np.argmax(scores))

    def update(self, arm: int, context: NDArray[np.float64], reward: float) -> None:
        if not 0 <= arm < len(self.a) or not np.isfinite(reward):
            raise ValueError("Invalid reward")
        self.a[arm] += np.outer(context, context)
        self.b[arm] += reward * context
