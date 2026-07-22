from __future__ import annotations

import pandas as pd
import pytest

from rsi_exit.divergence import (
    FORMAL_NEAR_HIGH_RETEST,
    INTRADAY_POTENTIAL_RETEST,
    NON_COMPARABLE_PEAK,
    STRICT_NEW_HIGH,
    DivergenceTracker,
    classify_peak_pair,
    classify_price_relation,
    comparable_zone,
)
from rsi_exit.models import Peak, SignalType


def make_peak(
    number: int,
    *,
    index: int,
    high: float,
    close: float,
    rsi: float,
    previous_close: float,
) -> Peak:
    date = pd.Timestamp("2026-01-01") + pd.offsets.BDay(index)
    return Peak(
        peak_id=f"P{number:04d}",
        peak_index=index,
        peak_date=date,
        confirm_index=index + 1,
        confirm_date=date + pd.offsets.BDay(1),
        earliest_action_date=date + pd.offsets.BDay(2),
        peak_close=close,
        peak_rsi=rsi,
        confirm_close=close - 1,
        confirm_rsi=rsi - 2,
        days_from_previous_peak=None,
        interim_min_close=None,
        interim_min_rsi=None,
        price_retrace_pct=None,
        rsi_retrace=None,
        is_independent_peak=True,
        merged_into_peak_id=None,
        previous_peak_id=None,
        peak_high=high,
        previous_day_close=previous_close,
    )


@pytest.mark.parametrize(
    ("previous_close", "peak_close", "expected"),
    [(98.0, 100.0, (98.0, 100.0)), (102.0, 100.0, (100.0, 102.0))],
)
def test_comparable_zone_uses_min_max_without_inversion(
    previous_close: float, peak_close: float, expected: tuple[float, float]
) -> None:
    previous = make_peak(
        1, index=0, high=105, close=peak_close, rsi=80,
        previous_close=previous_close,
    )
    assert comparable_zone(previous) == expected


@pytest.mark.parametrize(
    ("high", "close", "expected"),
    [
        (110.0001, 90.0, STRICT_NEW_HIGH),
        (110.0, 98.0, FORMAL_NEAR_HIGH_RETEST),
        (109.0, 105.0, FORMAL_NEAR_HIGH_RETEST),
        (109.0, 97.99, INTRADAY_POTENTIAL_RETEST),
        (97.99, 97.0, NON_COMPARABLE_PEAK),
    ],
)
def test_price_relation_priority(
    high: float, close: float, expected: str
) -> None:
    previous = make_peak(
        1, index=0, high=110, close=100, rsi=80, previous_close=98
    )
    current = make_peak(
        2, index=4, high=high, close=close, rsi=75, previous_close=97
    )
    assert classify_price_relation(previous, current, price_epsilon=1e-8) == expected


@pytest.mark.parametrize(
    ("drop", "expected"),
    [
        (0.9, SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE),
        (1.0, SignalType.NEAR_HIGH_BEARISH_DIVERGENCE),
    ],
)
def test_local_rsi_drop_boundary(drop: float, expected: SignalType) -> None:
    previous = make_peak(
        1, index=0, high=110, close=100, rsi=80, previous_close=98
    )
    current = make_peak(
        2, index=4, high=110, close=99, rsi=80 - drop, previous_close=97
    )
    signal, _, _ = classify_peak_pair(previous, current)
    assert signal == expected


@pytest.mark.parametrize("case", ["local_only", "anchor_only"])
def test_formal_divergence_requires_local_and_anchor_rsi_checks(case: str) -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    if case == "local_only":
        tracker.process(make_peak(
            1, index=4, high=101, close=100, rsi=81.9, previous_close=99
        ))
        result = tracker.process(make_peak(
            2, index=8, high=102, close=101, rsi=80.9, previous_close=100
        ))
    else:
        tracker.process(make_peak(
            1, index=4, high=101, close=100, rsi=75, previous_close=99
        ))
        result = tracker.process(make_peak(
            2, index=8, high=102, close=101, rsi=74.1, previous_close=100
        ))
    assert result.signal_type == SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE
    assert not result.position_eligible


@pytest.mark.parametrize(
    ("increase", "reset"), [(1.999, False), (2.0, True)]
)
def test_anchor_breakout_boundary(increase: float, reset: bool) -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    result = tracker.process(make_peak(
        1, index=4, high=101, close=100, rsi=80 + increase, previous_close=99
    ))
    assert (result.chain_reset_reason == "ANCHOR_RSI_BREAKOUT") is reset
    assert tracker.anchor.peak_rsi == (80 + increase if reset else 80)
    assert tracker.divergence_count == 0


def test_structural_peak_without_divergence_updates_last_not_count() -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    result = tracker.process(make_peak(
        1, index=4, high=101, close=100, rsi=79.5, previous_close=99
    ))
    assert result.signal_type == SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE
    assert tracker.last_structural_peak.representative_candidate_id == "P0001"
    assert tracker.anchor.representative_candidate_id == "P0000"
    assert tracker.divergence_count == 0


def test_non_comparable_peak_does_not_update_structural_state() -> None:
    tracker = DivergenceTracker()
    anchor = make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    )
    tracker.process(anchor)
    result = tracker.process(make_peak(
        1, index=4, high=90, close=89, rsi=70, previous_close=88
    ))
    assert result.signal_type == SignalType.NON_COMPARABLE_PEAK
    assert tracker.last_structural_peak.peak_date == anchor.peak_date
    assert tracker.divergence_count == 0


@pytest.mark.parametrize(("gap", "reset"), [(28, False), (29, True)])
def test_structural_gap_boundary(gap: int, reset: bool) -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    result = tracker.process(make_peak(
        1, index=gap, high=101, close=100, rsi=75, previous_close=99
    ))
    assert (result.chain_reset_reason == "STRUCTURAL_PEAK_GAP") is reset
    assert result.divergence_count == (0 if reset else 1)


@pytest.mark.parametrize(
    ("between", "reset"),
    [
        ([49.0, 49.0, 49.0], True),
        ([49.0, 50.0, 49.0], False),
        ([40.0], True),
        ([40.1], False),
    ],
)
def test_deep_rsi_reset_boundaries(between: list[float], reset: bool) -> None:
    current_index = len(between) + 1
    tracker = DivergenceTracker(rsi_values=[80.0, *between, 75.0])
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    result = tracker.process(make_peak(
        1, index=current_index, high=101, close=100, rsi=75, previous_close=99
    ))
    assert (result.chain_reset_reason == "DEEP_RSI_RESET") is reset
    assert result.divergence_count == (0 if reset else 1)


def test_low_peaks_do_not_break_consecutive_divergence_chain() -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    tracker.process(make_peak(
        1, index=4, high=101, close=100, rsi=77, previous_close=99
    ))
    for number, index in ((2, 8), (3, 12)):
        tracker.process(make_peak(
            number, index=index, high=90, close=89, rsi=70, previous_close=88
        ))
    result = tracker.process(make_peak(
        4, index=16, high=102, close=101, rsi=74, previous_close=100
    ))
    assert result.signal_type == SignalType.NEW_HIGH_BEARISH_DIVERGENCE
    assert result.divergence_count == 2


def test_intervening_non_divergence_structural_peak_preserves_count() -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    tracker.process(make_peak(
        1, index=4, high=101, close=100, rsi=77, previous_close=99
    ))
    middle = tracker.process(make_peak(
        2, index=8, high=102, close=101, rsi=77.5, previous_close=100
    ))
    final = tracker.process(make_peak(
        3, index=12, high=103, close=102, rsi=76.5, previous_close=101
    ))
    assert middle.signal_type == SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE
    assert final.signal_type == SignalType.NEW_HIGH_BEARISH_DIVERGENCE
    assert final.divergence_count == 2


def test_near_high_after_third_divergence_continues_chain() -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=100, close=99, rsi=80, previous_close=98
    ))
    for number, values in enumerate(
        [(101, 100, 77), (102, 101, 74), (103, 102, 71)], start=1
    ):
        tracker.process(make_peak(
            number, index=number * 4, high=values[0], close=values[1],
            rsi=values[2], previous_close=values[1] - 1,
        ))
    result = tracker.process(make_peak(
        4, index=16, high=103, close=101, rsi=68, previous_close=100
    ))
    assert result.signal_type == SignalType.NEAR_HIGH_BEARISH_DIVERGENCE
    assert result.divergence_count == 4


def test_strict_new_high_ignores_close_rejection() -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=110, close=100, rsi=80, previous_close=98
    ))
    result = tracker.process(make_peak(
        1, index=4, high=111, close=97, rsi=75, previous_close=96
    ))
    assert result.signal_type == SignalType.NEW_HIGH_BEARISH_DIVERGENCE
    assert result.close_rejected_from_high_zone


def test_peak_seven_to_eight_near_high_is_formal_divergence() -> None:
    tracker = DivergenceTracker()
    tracker.process(make_peak(
        0, index=0, high=120, close=110, rsi=85, previous_close=108
    ))
    peak_7 = make_peak(
        7, index=20, high=130, close=125, rsi=78, previous_close=123
    )
    tracker.process(peak_7)
    result = tracker.process(make_peak(
        8, index=24, high=129.5, close=124, rsi=76, previous_close=122
    ))
    assert result.signal_type == SignalType.NEAR_HIGH_BEARISH_DIVERGENCE
    assert result.price_relation == FORMAL_NEAR_HIGH_RETEST
    assert result.signal_type != SignalType.LOWER_HIGH_WEAK_REBOUND
