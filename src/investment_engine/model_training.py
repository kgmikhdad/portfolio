"""Manual price-only candidate research. Never promotes a policy or places trades."""

import os
import time
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import Engine, select

from investment_engine.data import DataUnavailable, digest, point_in_time_bars
from investment_engine.db import transaction
from investment_engine.models import Account, Decision, Experiment, Prediction, Security


def feature_vector(prices: list[float], index: int) -> list[float]:
    if index < 250:
        raise ValueError("At least 251 observations required")
    p = np.asarray(prices, dtype=np.float64)
    if np.any(p <= 0) or not np.all(np.isfinite(p)):
        raise ValueError("Finite positive adjusted prices required")
    return [
        *[float(p[index] / p[index - h] - 1) for h in (20, 60, 120, 250)],
        float(np.std(np.diff(np.log(p[index - 20 : index + 1])), ddof=1) * np.sqrt(252)),
        float(p[index] / p[index - 19 : index + 1].mean() - 1),
    ]


def fit_candidate(series: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    samples, targets, times, ends = [], [], [], []
    latest = []
    for item in series:
        prices, days = item["prices"], item["days"]
        if len(prices) < 251:
            continue
        latest.append((item["isin"], feature_vector(prices, len(prices) - 1)))
        for index in range(250, len(prices) - horizon):
            samples.append(feature_vector(prices, index))
            targets.append(prices[index + horizon] / prices[index] - 1)
            times.append(days[index])
            ends.append(days[index + horizon])
    dates = sorted(set(times))
    if len(dates) < 150:
        raise DataUnavailable("Insufficient matured historical targets")
    first_cut, second_cut = dates[int(len(dates) * 0.7)], dates[int(len(dates) * 0.85)]
    x, y = np.asarray(samples), np.asarray(targets)
    t, label_end = np.asarray(times), np.asarray(ends)
    train = (t < first_cut) & (label_end < first_cut - 7)
    validation = (t >= first_cut) & (t < second_cut)
    test = t >= second_cut
    if sum(train) < 200 or sum(validation) < 50 or sum(test) < 50:
        raise DataUnavailable("Insufficient purged train/validation/test observations")
    model = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    model.fit(x[train], y[train])
    validation_error = model.predict(x[validation]) - y[validation]
    test_error = model.predict(x[test]) - y[test]
    sigma = float(np.std(model.predict(x[train]) - y[train]))
    forecasts = [
        {"isin": isin, "estimate": float(model.predict([vector])[0]), "uncertainty": sigma}
        for isin, vector in latest
    ]
    metrics = {
        "training_observations": int(sum(train)),
        "validation_observations": int(sum(validation)),
        "test_observations": int(sum(test)),
        "validation_mse": float(np.mean(validation_error**2)),
        "untouched_test_mse": float(np.mean(test_error**2)),
        "cash_zero_return_test_mse": float(np.mean(y[test] ** 2)),
        "train_mean_test_mse": float(np.mean((y[test] - y[train].mean()) ** 2)),
        "purging_verified": bool(np.max(label_end[train]) < first_cut - 7),
        "uncertainty_status": "training_residual_scale_not_calibrated",
        "dataset_mode": "retrospective_vendor_vintage_current_universe",
        "survivorship_bias_unresolved": True,
        "fundamentals_missing": True,
        "promotion_approved": False,
        "final_test_used_for_tuning": False,
        "training_date_cutoff_ordinal": first_cut,
        "test_date_start_ordinal": second_cut,
    }
    parameters = {
        "algorithm": "StandardScaler+Ridge",
        "alpha": 10.0,
        "feature_names": [
            "momentum20",
            "momentum60",
            "momentum120",
            "momentum250",
            "volatility20",
            "sma20_ratio",
        ],
        "scaler_mean": model[0].mean_.tolist(),
        "scaler_scale": model[0].scale_.tolist(),
        "coefficients": model[1].coef_.tolist(),
        "intercept": float(model[1].intercept_),
        "horizon": horizon,
        "residual_scale": sigma,
        "embargo_calendar_days": 7,
    }
    return {"metrics": metrics, "parameters": parameters, "predictions": forecasts}


def train_candidates(db: Engine) -> dict[str, Any]:
    now = int(time.time())
    series, hashes = [], []
    with transaction(db) as session:
        account = session.get(Account, "paper")
        if account is None or not account.stopped:
            raise DataUnavailable("Stopped paper account required for candidate research")
        for security in session.scalars(select(Security).order_by(Security.isin)):
            bars = point_in_time_bars(session, security.isin, now)
            if not bars or now - bars[-1].published_at > 7 * 86400:
                continue
            if any(bar.adjusted_close_paise is None for bar in bars):
                continue
            from datetime import date

            series.append(
                {
                    "isin": security.isin,
                    "prices": [float(b.adjusted_close_paise or 0) for b in bars],
                    "days": [date.fromisoformat(b.day).toordinal() for b in bars],
                }
            )
            hashes.append({"isin": security.isin, "prices": [b.content_hash for b in bars]})
    dataset_hash = digest(hashes)
    code = os.environ.get("GITHUB_SHA", "local-research")
    completed, skipped = [], []
    for horizon in (20, 60, 120, 250):
        identifier = digest(
            {
                "dataset": dataset_hash,
                "horizon": horizon,
                "code": code,
                "algorithm": "ridge-price-only-v1",
            }
        )
        with transaction(db) as session:
            if session.get(Experiment, identifier):
                completed.append(horizon)
                continue
        try:
            result = fit_candidate(series, horizon)
        except DataUnavailable:
            skipped.append(horizon)
            continue
        with transaction(db) as session:
            session.add(
                Experiment(
                    id=identifier,
                    model_kind=f"ridge-price-only-{horizon}",
                    dataset_hash=dataset_hash,
                    code_version=code,
                    seed=42,
                    parameters=result["parameters"],
                    metrics=result["metrics"],
                    created_at=now,
                    status="experimental",
                )
            )
            session.flush()
            session.add_all(
                Prediction(
                    experiment_id=identifier,
                    isin=p["isin"],
                    as_of=now,
                    horizon=horizon,
                    estimate=p["estimate"],
                    uncertainty=p["uncertainty"],
                )
                for p in result["predictions"]
            )
        completed.append(horizon)
    return {
        "models_registered": len(completed),
        "horizons": completed,
        "skipped_horizons": skipped,
        "status": "experimental_only",
        "models_promoted": 0,
    }


def refresh_predictions(db: Engine) -> dict[str, Any]:
    """Apply fixed candidate parameters to new observations; never retrain/promote a model."""
    from sqlalchemy import func

    from investment_engine.market_pipeline import recent_feature_bars

    now = int(time.time())
    with transaction(db) as session:
        account = session.get(Account, "paper")
        if account is None or not account.stopped:
            raise DataUnavailable("Stopped paper account required for experimental inference")
        models: dict[int, Experiment] = {}
        for experiment in session.scalars(
            select(Experiment)
            .where(Experiment.status == "experimental")
            .order_by(Experiment.created_at.desc(), Experiment.id)
        ):
            horizon = experiment.parameters.get("horizon")
            if horizon in (20, 60, 120, 250) and horizon not in models:
                models[horizon] = experiment
        if not models:
            return {"forecasts_updated": 0, "models_retrained": 0, "models_promoted": 0}
        residual_scales = {}
        for experiment in models.values():
            uncertainty = experiment.parameters.get("residual_scale")
            if uncertainty is None:
                uncertainty = session.scalar(
                    select(func.max(Prediction.uncertainty)).where(
                        Prediction.experiment_id == experiment.id
                    )
                )
            residual_scales[experiment.id] = uncertainty
        prepared = []
        for security in session.scalars(select(Security).order_by(Security.isin)):
            bars = recent_feature_bars(session, security.isin, now)
            if len(bars) < 251 or now - bars[-1].published_at > 7 * 86400:
                continue
            if any(b.adjusted_close_paise is None for b in bars):
                continue
            vector = np.asarray(
                feature_vector([float(b.adjusted_close_paise or 0) for b in bars], len(bars) - 1)
            )
            input_hash = digest([b.content_hash for b in bars])
            for horizon, experiment in models.items():
                parameters = experiment.parameters
                mean = np.asarray(parameters["scaler_mean"])
                scale = np.asarray(parameters["scaler_scale"])
                coefficients = np.asarray(parameters["coefficients"])
                if mean.shape != vector.shape or np.any(scale <= 0):
                    raise DataUnavailable("Candidate parameter contract mismatch")
                estimate = float(((vector - mean) / scale) @ coefficients + parameters["intercept"])
                uncertainty = residual_scales[experiment.id]
                if uncertainty is None or not np.isfinite(estimate) or not np.isfinite(uncertainty):
                    continue
                identifier = digest(
                    {
                        "model": experiment.id,
                        "isin": security.isin,
                        "inputs": input_hash,
                        "policy": "experimental-inference-v1",
                    }
                )
                prepared.append(
                    {
                        "id": identifier,
                        "isin": security.isin,
                        "experiment": experiment.id,
                        "horizon": horizon,
                        "estimate": estimate,
                        "uncertainty": float(uncertainty),
                        "input_hash": input_hash,
                    }
                )
        known = (
            set(
                session.scalars(
                    select(Decision.id).where(Decision.id.in_([p["id"] for p in prepared]))
                )
            )
            if prepared
            else set()
        )
        updates = [p for p in prepared if p["id"] not in known]
        for prediction in updates:
            session.add(
                Decision(
                    id=prediction["id"],
                    account_id="paper",
                    isin=prediction["isin"],
                    at=now,
                    kind="experimental_model_forecast",
                    reason="Price-only candidate inference; not approved for trading",
                    evidence={
                        "experiment_id": prediction["experiment"],
                        "input_dataset_hash": prediction["input_hash"],
                        "horizon": prediction["horizon"],
                        "estimate": prediction["estimate"],
                        "approved": False,
                    },
                )
            )
            session.add(
                Prediction(
                    experiment_id=prediction["experiment"],
                    isin=prediction["isin"],
                    as_of=now,
                    horizon=prediction["horizon"],
                    estimate=prediction["estimate"],
                    uncertainty=prediction["uncertainty"],
                )
            )
    return {"forecasts_updated": len(updates), "models_retrained": 0, "models_promoted": 0}
