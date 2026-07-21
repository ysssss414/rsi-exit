from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from rsi_exit.divergence import DivergenceTracker, classify_peak_pair
from rsi_exit.models import Peak, SignalType


def peak(
    number: int,
    close: float,
    rsi: float,
    *,
    gap: int = 4,
    interim_rsi: float = 60.0,
) -> Peak:
    date = pd.Timestamp("2026-01-01") + pd.offsets.BDay(number * gap)
    return Peak(
        peak_id=f"P{number:04d}", peak_index=number * gap, peak_date=date,
        confirm_index=number * gap + 1, confirm_date=date + pd.offsets.BDay(1),
        earliest_action_date=date + pd.offsets.BDay(2), peak_close=close, peak_rsi=rsi,
        confirm_close=close * 0.99, confirm_rsi=rsi - 2, days_from_previous_peak=None if number == 1 else gap,
        interim_min_close=close * 0.95, interim_min_rsi=interim_rsi,
        price_retrace_pct=0.05, rsi_retrace=5.0, is_independent_peak=True,
        merged_into_peak_id=None, previous_peak_id=None if number == 1 else f"P{number-1:04d}",
    )


@pytest.mark.parametrize(
    ("current_close", "current_rsi", "expected"),
    [
        (101.0, 82.0, SignalType.TREND_STRENGTHENING),
        (101.0, 78.0, SignalType.BEARISH_DIVERGENCE),
        (99.5, 78.0, SignalType.BEARISH_DIVERGENCE),
        (99.49, 78.0, SignalType.LOWER_HIGH_WEAK_REBOUND),
        (99.49, 80.0, SignalType.LOWER_PRICE_RSI_IMPROVING),
    ],
)
def test_four_way_classification(current_close: float, current_rsi: float, expected: SignalType) -> None:
    previous = peak(1, 100.0, 80.0)
    current = peak(2, current_close, current_rsi)
    actual, _, _ = classify_peak_pair(previous, current)
    assert actual == expected


def test_rsi_exact_lower_tolerance_boundary_does_not_report_divergence() -> None:
    actual, _, relation = classify_peak_pair(peak(1, 100, 80), peak(2, 100, 79))
    assert actual == SignalType.TREND_STRENGTHENING
    assert relation == "RSI_FLAT_WITHIN_TOLERANCE"


def test_price_exact_tolerance_boundary_is_near_high() -> None:
    actual, relation, _ = classify_peak_pair(peak(1, 100, 80), peak(2, 99.5, 78))
    assert actual == SignalType.BEARISH_DIVERGENCE
    assert relation == "PRICE_NEW_OR_NEAR_HIGH"


def test_consecutive_first_second_third_divergence() -> None:
    tracker = DivergenceTracker()
    assert tracker.process(peak(1, 100, 80)) is None
    assert tracker.process(peak(2, 101, 77)).divergence_count == 1
    assert tracker.process(peak(3, 102, 74)).divergence_count == 2
    assert tracker.process(peak(4, 103, 71)).divergence_count == 3


def test_rsi_new_high_resets_divergence() -> None:
    tracker = DivergenceTracker()
    tracker.process(peak(1, 100, 80))
    tracker.process(peak(2, 101, 77))
    result = tracker.process(peak(3, 102, 79))
    assert result.signal_type == SignalType.TREND_STRENGTHENING
    assert result.divergence_count == 0


def test_gap_over_30_resets_before_counting_pair() -> None:
    tracker = DivergenceTracker()
    tracker.process(peak(1, 100, 80))
    second = replace(peak(2, 101, 75), days_from_previous_peak=31)
    result = tracker.process(second)
    assert result.divergence_count == 0
    assert result.reset_reason == "PEAK_GAP_EXCEEDED"


def test_interim_rsi_below_50_resets_before_counting_pair() -> None:
    tracker = DivergenceTracker()
    tracker.process(peak(1, 100, 80))
    result = tracker.process(peak(2, 101, 75, interim_rsi=49))
    assert result.divergence_count == 0
    assert result.reset_reason == "INTERIM_RSI_BELOW_RESET_LEVEL"


def test_weak_rebound_does_not_increase_count() -> None:
    tracker = DivergenceTracker()
    tracker.process(peak(1, 100, 80))
    tracker.process(peak(2, 101, 77))
    result = tracker.process(peak(3, 95, 73))
    assert result.signal_type == SignalType.LOWER_HIGH_WEAK_REBOUND
    assert result.divergence_count == 1


def test_merged_candidate_does_not_emit_or_increment() -> None:
    tracker = DivergenceTracker()
    first = peak(1, 100, 80)
    tracker.process(first)
    merged = replace(
        peak(2, 101, 79), is_independent_peak=False, merged_into_peak_id="P0001",
        canonical_updated=True,
    )
    assert tracker.process(merged) is None
    assert tracker.divergence_count == 0
    assert tracker.previous.peak_id == "P0001"

