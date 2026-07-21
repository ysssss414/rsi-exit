from __future__ import annotations

import pandas as pd

from rsi_exit.peak_detector import PeakDetector


def frame(close: list[float], rsi: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"date": pd.bdate_range("2026-01-01", periods=len(close)), "close": close, "rsi14": rsi}
    )


def test_price_and_rsi_fall_confirm_peak() -> None:
    peaks, events = PeakDetector().detect(frame([10, 11, 12, 11, 10], [50, 60, 70, 65, 55]))
    assert len(peaks) == 1
    assert peaks.iloc[0]["peak_date"] == "2026-01-05"
    assert peaks.iloc[0]["confirm_date"] == "2026-01-06"
    assert peaks.iloc[0]["earliest_action_date"] == "2026-01-07"
    assert pd.Timestamp("2026-01-06") in events


def test_price_falls_but_rsi_does_not_fall_no_confirmation() -> None:
    peaks, _ = PeakDetector().detect(frame([10, 11, 12, 11], [50, 60, 70, 71]))
    assert peaks.empty


def test_rsi_falls_but_price_does_not_fall_no_confirmation() -> None:
    peaks, _ = PeakDetector().detect(frame([10, 11, 12, 13], [50, 60, 70, 65]))
    assert peaks.empty


def test_continuous_rise_is_not_confirmed_early() -> None:
    peaks, _ = PeakDetector().detect(frame([10, 11, 12, 13, 14], [50, 55, 60, 65, 70]))
    assert peaks.empty


def test_same_wave_small_peaks_are_merged() -> None:
    peaks, _ = PeakDetector().detect(
        frame([8, 9, 10, 9.5, 10.2, 9.8], [40, 50, 70, 60, 71, 65])
    )
    assert len(peaks) == 2
    assert bool(peaks.iloc[0]["is_independent_peak"])
    assert not bool(peaks.iloc[1]["is_independent_peak"])
    assert peaks.iloc[1]["merged_into_peak_id"] == "P0001"
    assert bool(peaks.iloc[1]["canonical_updated"])


def test_retrace_and_gap_create_new_independent_peak() -> None:
    peaks, _ = PeakDetector().detect(
        frame([8, 9, 10, 9, 8, 9, 11, 10], [40, 50, 70, 60, 55, 60, 68, 65])
    )
    independent = peaks.loc[peaks["is_independent_peak"]]
    assert len(independent) == 2
    assert independent.iloc[1]["days_from_previous_peak"] == 4
    assert independent.iloc[1]["rsi_retrace"] == 15.0


def test_no_future_function_candidate_appears_only_after_confirm_bar() -> None:
    detector = PeakDetector()
    through_peak, _ = detector.detect(frame([10, 11, 12], [50, 60, 70]))
    through_confirm, _ = detector.detect(frame([10, 11, 12, 11], [50, 60, 70, 65]))
    assert through_peak.empty
    assert len(through_confirm) == 1
    assert through_confirm.iloc[0]["confirm_date"] > through_confirm.iloc[0]["peak_date"]


def test_no_retrace_means_merge_even_when_gap_is_large_enough() -> None:
    peaks, _ = PeakDetector().detect(
        frame([8, 9, 10, 9.9, 10.0, 10.1, 10.2, 10.0], [50, 60, 70, 69, 69.5, 70, 71, 68])
    )
    assert len(peaks) == 2
    assert not bool(peaks.iloc[1]["is_independent_peak"])

