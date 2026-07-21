from __future__ import annotations

import numpy as np
import pandas as pd

from rsi_exit.config import load_config
from rsi_exit.pipeline import analyze_bars, run_batch


def bars() -> pd.DataFrame:
    close = np.array(
        [100, 102, 104, 103, 101, 103, 106, 105, 102, 104,
         108, 106, 103, 105, 109, 107, 104, 106, 110, 108,
         105, 107, 111, 109, 106, 108, 112, 110, 107, 109,
         113, 111, 108, 110, 114, 112, 109, 111, 115, 113],
        dtype=float,
    )
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=len(close)),
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.arange(len(close)) + 1000,
            "amount": close * (np.arange(len(close)) + 1000),
        }
    )


def test_pipeline_outputs_required_contract() -> None:
    source = bars()
    source.attrs.update(source="synthetic", adjust="forward")
    result = analyze_bars(source, symbol="300308.SZ", name="sample", config=load_config())
    assert {
        "date", "ma20", "rsi14", "rsi_zone", "base_state", "base_action",
        "base_position_cap", "final_action", "final_position_cap",
    } <= set(result.daily_features.columns)
    assert {
        "peak_id", "peak_date", "confirm_date", "earliest_action_date",
        "is_independent_peak", "merged_into_peak_id",
    } <= set(result.peaks.columns)
    assert set(result.signals.columns) >= {
        "signal_date", "earliest_action_date", "signal_type", "final_position_cap"
    }
    assert result.metadata["seed_mode"] == "first"
    assert result.metadata["adjust"] == "forward"


def test_all_peak_confirm_and_action_dates_are_causal() -> None:
    result = analyze_bars(bars(), symbol="300308.SZ", config=load_config())
    non_terminal = result.peaks.dropna(subset=["earliest_action_date"])
    assert (
        pd.to_datetime(result.peaks["confirm_date"])
        > pd.to_datetime(result.peaks["peak_date"])
    ).all()
    assert (
        pd.to_datetime(non_terminal["earliest_action_date"])
        > pd.to_datetime(non_terminal["confirm_date"])
    ).all()
    if not result.signals.empty:
        assert (
            pd.to_datetime(result.signals["earliest_action_date"])
            > pd.to_datetime(result.signals["signal_date"])
        ).all()


def test_batch_summary_contract() -> None:
    _, summary = run_batch(
        [("300308.SZ", "sample", bars())], config=load_config()
    )
    assert len(summary) == 1
    assert {
        "symbol", "name", "peak_count", "divergence_count_1",
        "divergence_count_2", "divergence_count_3", "warnings",
    } <= set(summary.columns)

