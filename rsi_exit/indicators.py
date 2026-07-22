from __future__ import annotations

import numpy as np
import pandas as pd


def cn_sma(
    series: pd.Series,
    n: int = 14,
    m: int = 1,
    seed_mode: str = "first",
) -> pd.Series:
    """Domestic-formula SMA: Y_t = (M*X_t + (N-M)*Y_(t-1)) / N.

    ``first`` seeds at the first non-null X. ``mean`` waits for N non-null
    observations, seeds with their arithmetic mean, then uses the same recurrence.
    A null X yields a null output for that row but does not erase the last state.
    """
    if not isinstance(series, pd.Series):
        series = pd.Series(series, dtype="float64")
    if not isinstance(n, int) or n <= 0:
        raise ValueError("n 必须是正整数")
    if not isinstance(m, int) or m <= 0 or m > n:
        raise ValueError("m 必须是 1..n 的整数")
    if seed_mode not in {"first", "mean"}:
        raise ValueError("seed_mode 必须是 first 或 mean")

    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)
    previous: float | None = None
    seed_values: list[float] = []

    for i, value in enumerate(values):
        if np.isnan(value):
            continue
        if previous is None:
            if seed_mode == "first":
                previous = float(value)
                output[i] = previous
            else:
                seed_values.append(float(value))
                if len(seed_values) == n:
                    previous = float(np.mean(seed_values))
                    output[i] = previous
            continue
        previous = (m * float(value) + (n - m) * previous) / n
        output[i] = previous
    return pd.Series(output, index=series.index, name=series.name, dtype="float64")


def calculate_rsi_cn(
    close: pd.Series,
    period: int = 14,
    seed_mode: str = "first",
) -> pd.Series:
    """Calculate RSI14 using the domestic LC/SMA formula."""
    audit = calculate_rsi_audit(close, period=period, seed_mode=seed_mode)
    rsi = audit["rsi"]
    rsi.name = f"rsi{period}"
    return rsi


def calculate_rsi_audit(
    close: pd.Series,
    period: int = 14,
    seed_mode: str = "first",
) -> pd.DataFrame:
    """Return every numeric component used by the domestic RSI recurrence."""
    numeric = pd.to_numeric(close, errors="coerce").astype("float64")
    delta = numeric.diff()
    gain = delta.clip(lower=0)
    absolute = delta.abs()
    smoothed_gain = cn_sma(gain, n=period, m=1, seed_mode=seed_mode)
    smoothed_absolute = cn_sma(absolute, n=period, m=1, seed_mode=seed_mode)
    denominator = smoothed_absolute.replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "adjusted_close": numeric,
            "delta": delta,
            "gain": gain,
            "absolute_delta": absolute,
            "smoothed_gain": smoothed_gain,
            "smoothed_absolute": smoothed_absolute,
            "rsi": smoothed_gain.div(denominator).mul(100.0),
        },
        index=numeric.index,
    )


def rsi_zone(value: float, *, strong: float = 70, life: float = 60,
             neutral: float = 50, weak: float = 40) -> str:
    if pd.isna(value):
        return "UNAVAILABLE"
    if value >= strong:
        return "ABOVE_70"
    if value >= life:
        return "60_TO_70"
    if value >= neutral:
        return "50_TO_60"
    if value >= weak:
        return "40_TO_50"
    return "BELOW_40"
