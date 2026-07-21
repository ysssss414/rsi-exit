from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rsi_exit.indicators import calculate_rsi_cn, cn_sma


def test_cn_sma_matches_hand_recurrence() -> None:
    values = pd.Series([2.0, 1.0, 3.0])
    actual = cn_sma(values, n=3, m=1, seed_mode="first")
    expected = pd.Series([2.0, 5.0 / 3.0, 19.0 / 9.0])
    pd.testing.assert_series_equal(actual, expected)


def test_cn_sma_mean_seed_waits_for_n_values() -> None:
    actual = cn_sma(pd.Series([1.0, 2.0, 3.0, 4.0]), n=3, seed_mode="mean")
    assert actual.iloc[:2].isna().all()
    assert actual.iloc[2] == pytest.approx(2.0)
    assert actual.iloc[3] == pytest.approx(8.0 / 3.0)


def test_rsi_monotonic_up_is_100() -> None:
    actual = calculate_rsi_cn(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert np.isnan(actual.iloc[0])
    assert (actual.iloc[1:] == 100.0).all()


def test_rsi_monotonic_down_is_zero() -> None:
    actual = calculate_rsi_cn(pd.Series([4.0, 3.0, 2.0, 1.0]))
    assert np.isnan(actual.iloc[0])
    assert (actual.iloc[1:] == 0.0).all()


def test_rsi_alternating_matches_manual_recurrence() -> None:
    close = pd.Series([100.0, 102.0, 101.0, 104.0])
    actual = calculate_rsi_cn(close)
    gain_2 = (0.0 + 13.0 * 2.0) / 14.0
    abs_2 = (1.0 + 13.0 * 2.0) / 14.0
    gain_3 = (3.0 + 13.0 * gain_2) / 14.0
    abs_3 = (3.0 + 13.0 * abs_2) / 14.0
    assert actual.iloc[1] == pytest.approx(100.0)
    assert actual.iloc[2] == pytest.approx(gain_2 / abs_2 * 100.0)
    assert actual.iloc[3] == pytest.approx(gain_3 / abs_3 * 100.0)


def test_rsi_missing_values_are_visible_and_state_resumes() -> None:
    actual = calculate_rsi_cn(pd.Series([100.0, 101.0, np.nan, 102.0, 103.0]))
    assert actual.iloc[[0, 2, 3]].isna().all()
    assert actual.iloc[1] == 100.0
    assert actual.iloc[4] == 100.0


def test_rsi_first_and_mean_seed_modes_differ_only_in_warmup_here() -> None:
    close = pd.Series(range(1, 18), dtype=float)
    first = calculate_rsi_cn(close, seed_mode="first")
    mean = calculate_rsi_cn(close, seed_mode="mean")
    assert first.first_valid_index() == 1
    assert mean.first_valid_index() == 14
    assert mean.iloc[14] == 100.0


def test_invalid_sma_parameters_fail_clearly() -> None:
    with pytest.raises(ValueError):
        cn_sma(pd.Series([1.0]), n=0)
    with pytest.raises(ValueError):
        cn_sma(pd.Series([1.0]), n=14, m=15)
    with pytest.raises(ValueError):
        cn_sma(pd.Series([1.0]), seed_mode="unknown")

