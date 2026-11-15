"""Deterministic, versioned features; missing inputs stay missing."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    inputs: str
    transform: str
    frequency: str = "daily"
    missing: str = "null; block models that require this feature"
    timestamp: str = "max(publication, receipt) of every input <= decision time"
    version: str = "1"


DEFINITIONS = [
    FeatureDefinition("momentum20", "21 adjusted closes", "close[t]/close[t-20]-1"),
    FeatureDefinition("momentum60", "61 adjusted closes", "close[t]/close[t-60]-1"),
    FeatureDefinition("volatility20", "21 adjusted closes", "std(log returns, ddof=1)*sqrt(252)"),
    FeatureDefinition("rsi14", "15 adjusted closes", "14-period arithmetic RSI"),
    FeatureDefinition("sma20_ratio", "20 adjusted closes", "close/mean(20)-1"),
    FeatureDefinition("drawdown", "available adjusted closes", "close/running maximum-1"),
    FeatureDefinition("earnings_yield", "positive earnings, market cap", "earnings/market cap"),
    FeatureDefinition("roe", "net income, positive mean equity", "net income/mean equity"),
    FeatureDefinition("cash_conversion", "CFO, positive net income", "CFO/net income"),
    FeatureDefinition("debt_equity", "debt, positive equity", "debt/equity"),
    FeatureDefinition("growth", "current and positive previous period", "current/previous-1"),
]


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def total_return_prices(
    closes: Sequence[float],
    splits: dict[int, float],
    dividends: dict[int, float],
) -> NDArray[np.float64]:
    """Forward total-return index. Actions must already pass point-in-time eligibility.

    split ratio is new shares / old shares; dividend is cash per pre-action share.
    Same-day split+dividend ambiguity must be normalized by the provider before calling.
    """
    prices = np.asarray(closes, dtype=np.float64)
    if len(prices) == 0 or not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("Positive finite closes required")
    result = np.zeros(len(prices), dtype=np.float64)
    result[0] = prices[0]
    for i in range(1, len(prices)):
        split = splits.get(i, 1.0)
        dividend = dividends.get(i, 0.0)
        if split <= 0 or dividend < 0:
            raise ValueError("Invalid corporate action")
        result[i] = result[i - 1] * (prices[i] * split + dividend) / prices[i - 1]
    return result


def technical(prices: Sequence[float]) -> dict[str, float | None]:
    p = np.asarray(prices, dtype=np.float64)
    if len(p) == 0 or np.any(p <= 0) or not np.all(np.isfinite(p)):
        raise ValueError("Valid adjusted prices required")
    result: dict[str, float | None] = {
        "momentum20": float(p[-1] / p[-21] - 1) if len(p) >= 21 else None,
        "momentum60": float(p[-1] / p[-61] - 1) if len(p) >= 61 else None,
        "sma20_ratio": float(p[-1] / p[-20:].mean() - 1) if len(p) >= 20 else None,
        "volatility20": (
            float(np.std(np.diff(np.log(p[-21:])), ddof=1) * np.sqrt(252)) if len(p) >= 21 else None
        ),
        "drawdown": float(p[-1] / np.max(p) - 1),
        "rsi14": None,
    }
    if len(p) >= 15:
        changes = np.diff(p[-15:])
        up, down = np.maximum(changes, 0).mean(), np.maximum(-changes, 0).mean()
        result["rsi14"] = float(100 - 100 / (1 + up / down)) if down else (100.0 if up else 50.0)
    return result
