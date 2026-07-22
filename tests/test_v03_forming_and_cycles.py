from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.divergence import DivergenceTracker
from rsi_exit.models import FormingPeakEvent, Peak, SignalType
from rsi_exit.peak_detector import PeakDetector
from rsi_exit.pipeline import analyze_bars


def detector_frame(close: list[float], rsi: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=len(close)),
        "high": close,
        "close": close,
        "rsi14": rsi,
    })


def test_forming_peak_extends_then_confirms_latest_representative() -> None:
    frame = detector_frame([10, 11, 12, 11], [50, 60, 70, 65])
    detector = PeakDetector()
    peaks, _ = detector.detect(frame)
    first = detector.forming_events[pd.Timestamp(frame.iloc[1]["date"])][0]
    extended = detector.forming_events[pd.Timestamp(frame.iloc[2]["date"])][0]
    assert first.forming_peak_id == extended.forming_peak_id
    assert (first.forming_version, extended.forming_version) == (1, 2)
    assert peaks.iloc[0]["peak_date"] == frame.iloc[2]["date"].strftime("%Y-%m-%d")
    assert peaks.iloc[0]["confirm_date"] == frame.iloc[3]["date"].strftime("%Y-%m-%d")


def test_invalidated_forming_peak_leaves_no_confirmed_candidate() -> None:
    frame = detector_frame([10, 11, 10.5, 10.7], [50, 60, 61, 60])
    detector = PeakDetector()
    peaks, _ = detector.detect(frame)
    assert len(detector.forming_events) == 1
    assert peaks.empty


def tracker_peak(number: int, index: int, high: float, close: float, rsi: float) -> Peak:
    date = pd.Timestamp("2026-01-01") + pd.offsets.BDay(index)
    return Peak(
        peak_id=f"P{number:04d}", peak_index=index, peak_date=date,
        confirm_index=index + 1, confirm_date=date + pd.offsets.BDay(1),
        earliest_action_date=date + pd.offsets.BDay(2), peak_high=high,
        peak_close=close, peak_rsi=rsi, previous_day_close=close - 1,
        confirm_close=close - 1, confirm_rsi=rsi - 2,
        days_from_previous_peak=None, interim_min_close=None,
        interim_min_rsi=None, price_retrace_pct=None, rsi_retrace=None,
        is_independent_peak=True, merged_into_peak_id=None,
        previous_peak_id=None,
    )


def test_forming_preview_is_non_mutating_and_position_ineligible() -> None:
    tracker = DivergenceTracker()
    tracker.process(tracker_peak(0, 0, 100, 99, 80))
    before = (
        tracker.last_structural_peak.peak_date,
        tracker.anchor.peak_date,
        tracker.divergence_count,
        tracker.divergence_chain_id,
    )
    forming = FormingPeakEvent(
        forming_peak_id="FPK0001", forming_version=1, peak_index=4,
        peak_date=pd.Timestamp("2026-01-07"), peak_high=101,
        peak_close=100, peak_rsi=75, previous_day_close=99,
    )
    result = tracker.preview_forming(forming, risk_cycle_id="CYCLE0007")
    after = (
        tracker.last_structural_peak.peak_date,
        tracker.anchor.peak_date,
        tracker.divergence_count,
        tracker.divergence_chain_id,
    )
    assert result.signal_type == SignalType.DIVERGENCE_FORMING
    assert result.signal_status == "FORMING"
    assert not result.position_eligible
    assert before == after


def scripted_bars() -> tuple[pd.DataFrame, pd.Series]:
    count = 40
    index = np.arange(count)
    close = 90 + index * 0.02
    rsi = pd.Series(65.0, index=index)
    for peak_index, peak_close, peak_rsi in (
        (10, 100, 80), (16, 101, 77), (22, 102, 74), (28, 103, 71)
    ):
        close[peak_index - 1 : peak_index + 2] = [peak_close - 2, peak_close, peak_close - 3]
        rsi.iloc[peak_index - 1 : peak_index + 2] = [70, peak_rsi, 68]
    source = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=count),
        "open": close - 0.2,
        "high": close,
        "low": close - 0.5,
        "close": close,
        "volume": 1000 + index,
        "amount": close * (1000 + index),
    })
    source["hard_exit"] = 0
    source.loc[24, "hard_exit"] = 1
    source.loc[25, "close"] = 95
    source.loc[25, "high"] = 95
    source.loc[25, "open"] = 94.8
    source.loc[25, "low"] = 94.5
    source.loc[25, "amount"] = source.loc[25, "close"] * source.loc[25, "volume"]
    rsi.iloc[25] = 72
    return source, rsi


def install_scripted_rsi(monkeypatch, scripted_rsi: pd.Series) -> None:
    def fake_audit(close: pd.Series, period: int, seed_mode: str) -> pd.DataFrame:
        values = scripted_rsi.iloc[: len(close)].reset_index(drop=True)
        delta = close.reset_index(drop=True).diff()
        return pd.DataFrame({
            "adjusted_close": close.reset_index(drop=True),
            "delta": delta,
            "gain": delta.clip(lower=0),
            "absolute_delta": delta.abs(),
            "smoothed_gain": delta.clip(lower=0),
            "smoothed_absolute": delta.abs(),
            "rsi": values,
        })

    monkeypatch.setattr("rsi_exit.pipeline.calculate_rsi_audit", fake_audit)


def canonical_update_bars() -> tuple[pd.DataFrame, pd.Series]:
    count = 24
    index = np.arange(count)
    close = 90 + index * 0.02
    rsi = pd.Series(65.0, index=index)
    for peak_index, peak_close, peak_rsi, left_close, left_rsi in (
        (10, 100, 80, 98, 70),
        (16, 101, 77, 99, 70),
        (18, 102, 76, 98, 68),
    ):
        close[peak_index - 1 : peak_index + 2] = [left_close, peak_close, peak_close - 3]
        rsi.iloc[peak_index - 1 : peak_index + 2] = [left_rsi, peak_rsi, left_rsi - 1]
    source = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=count),
        "open": close - 0.2,
        "high": close,
        "low": close - 0.5,
        "close": close,
        "volume": 1000 + index,
        "amount": close * (1000 + index),
    })
    return source, rsi


def test_pipeline_merged_candidate_cannot_emit_or_change_position_state(monkeypatch) -> None:
    source, rsi = canonical_update_bars()
    install_scripted_rsi(monkeypatch, rsi)
    result = analyze_bars(source, symbol="CANONICAL.UPDATE", config=load_config())
    formal = result.signals.loc[
        (result.signals["signal_status"] == "FORMAL")
        & result.signals["signal_type"].isin({
            SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
            SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
        })
    ]
    assert formal["divergence_count"].tolist() == [1]
    assert formal["divergence_position_cap"].tolist() == [0.7]
    update = result.peaks.loc[result.peaks["canonical_updated"].astype(bool)].iloc[0]
    assert update["canonical_peak_id"] == formal.iloc[0]["canonical_peak_id"]
    assert update["candidate_peak_id"] not in set(result.signals["candidate_peak_id"])
    assert not bool(update["structural_eligible"])
    assert not bool(update["position_eligible"])
    assert "THIRD_DIVERGENCE" not in set(result.state_log["trigger"])


def test_pipeline_same_canonical_anchor_breakout_only_resets_divergence_chain(
    monkeypatch,
) -> None:
    count = 18
    index = np.arange(count)
    close = 90 + index * 0.02
    rsi = pd.Series(65.0, index=index)
    close[9:14] = [98, 100, 97, 102, 99]
    rsi.iloc[9:14] = [70, 80, 68, 82, 69]
    source = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=count),
        "open": close - 0.2,
        "high": close,
        "low": close - 0.5,
        "close": close,
        "volume": 1000 + index,
        "amount": close * (1000 + index),
    })
    install_scripted_rsi(monkeypatch, rsi)
    result = analyze_bars(source, symbol="CANONICAL.BREAKOUT", config=load_config())
    breakout = result.signals.loc[
        result.signals["same_canonical_anchor_breakout"].astype(bool)
    ]
    assert len(breakout) == 1
    row = breakout.iloc[0]
    assert row["chain_reset_reason"] == "ANCHOR_RSI_BREAKOUT"
    assert not bool(row["position_eligible"])
    assert row["pending_action_type"] is None
    assert row["decision_signal_position_cap"] == 1.0
    assert not result.cycle_log["reset_reason"].fillna("").str.contains(
        "ANCHOR_RSI_BREAKOUT"
    ).any()


def test_forming_rows_never_schedule_position_actions(monkeypatch) -> None:
    source, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    result = analyze_bars(source, symbol="FORMING.TEST", config=load_config())
    forming = result.signals.loc[result.signals["signal_status"] == "FORMING"]
    assert not forming.empty
    assert not forming["position_eligible"].astype(bool).any()
    assert forming["pending_action_type"].isna().all()
    assert (forming["divergence_position_cap"] == 1.0).all()
    assert not result.daily_features["effective_signal_source_candidate_peak_id"].astype(str).str.startswith("FPK").any()


def test_s3_and_allow_reentry_do_not_reset_divergence_chain(monkeypatch) -> None:
    source, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    result = analyze_bars(source, symbol="CYCLE.TEST", config=load_config())
    formal = result.signals.loc[
        result.signals["signal_type"].isin({
            SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
            SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
        })
    ]
    assert formal["divergence_count"].tolist() == [1, 2, 3]
    assert formal["divergence_chain_id"].nunique() == 1
    assert formal["risk_cycle_id"].nunique() >= 2
    assert "ALLOW_REENTRY" in set(result.state_log["state_event"].dropna())


def test_formal_signal_dates_are_strictly_causal(monkeypatch) -> None:
    source, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    result = analyze_bars(source, symbol="CAUSAL.TEST", config=load_config())
    formal = result.signals.loc[
        (result.signals["signal_status"] == "FORMAL")
        & result.signals["earliest_action_date"].notna()
    ]
    assert (
        pd.to_datetime(formal["current_peak_date"])
        < pd.to_datetime(formal["decision_date"])
    ).all()
    assert (
        pd.to_datetime(formal["decision_date"])
        < pd.to_datetime(formal["earliest_action_date"])
    ).all()


def test_prefix_run_cannot_rewrite_confirmed_formal_signals(monkeypatch) -> None:
    source, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    prefix = analyze_bars(source.iloc[:27], symbol="PREFIX.TEST", config=load_config())
    full = analyze_bars(source, symbol="PREFIX.TEST", config=load_config())
    columns = [
        "decision_date", "current_peak_date", "signal_type", "divergence_count",
        "previous_peak_date", "momentum_anchor_date", "divergence_chain_id",
    ]
    left = prefix.signals.loc[prefix.signals["signal_status"] == "FORMAL", columns]
    right = full.signals.loc[
        (full.signals["signal_status"] == "FORMAL")
        & (full.signals["decision_date"] <= source.iloc[26]["date"].strftime("%Y-%m-%d")),
        columns,
    ]
    pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))


def test_later_canonical_update_does_not_mutate_saved_result() -> None:
    tracker = DivergenceTracker()
    tracker.process(tracker_peak(0, 0, 100, 99, 80))
    saved = tracker.process(tracker_peak(1, 4, 101, 100, 77))
    snapshot = (
        saved.canonical_peak_id,
        saved.canonical_version,
        saved.divergence_count,
        saved.previous_peak_date,
    )
    update = replace(
        tracker_peak(2, 8, 102, 101, 76),
        is_independent_peak=False,
        canonical_peak_id="P0001",
        merged_into_peak_id="P0001",
        canonical_updated=True,
        canonical_version=2,
    )
    assert tracker.process(update) is None
    assert snapshot == (
        saved.canonical_peak_id,
        saved.canonical_version,
        saved.divergence_count,
        saved.previous_peak_date,
    )


def test_canonical_forming_updates_then_formally_confirms_only_once() -> None:
    tracker = DivergenceTracker()
    tracker.process(tracker_peak(0, 0, 100, 99, 80))
    for version, high, close, rsi in (
        (1, 100.5, 99.5, 78.0),
        (2, 101.0, 100.0, 77.0),
    ):
        forming = FormingPeakEvent(
            forming_peak_id="FPK-P0001", forming_version=version,
            peak_index=version + 2, peak_date=pd.Timestamp("2026-01-05") + pd.offsets.BDay(version),
            peak_high=high, peak_close=close, peak_rsi=rsi,
            previous_day_close=close - 1,
        )
        tracker.preview_forming(forming)

    confirmed = tracker_peak(1, 4, 101, 100, 77)
    formal = tracker.process(confirmed)
    assert formal.signal_type == SignalType.NEW_HIGH_BEARISH_DIVERGENCE
    assert formal.divergence_count == 1
    formal_snapshot = (
        formal.canonical_peak_id,
        formal.canonical_version,
        formal.signal_type,
        formal.divergence_count,
        confirmed.confirm_date,
        confirmed.earliest_action_date,
        tracker.last_structural_peak,
        tracker.anchor,
        tracker.divergence_chain_id,
    )

    later_candidate = replace(
        tracker_peak(2, 6, 102, 101, 76),
        is_independent_peak=False,
        merged_into_peak_id="P0001",
        canonical_peak_id="P0001",
        representative_candidate_id="P0002",
        canonical_updated=True,
        canonical_version=2,
    )
    assert tracker.process(later_candidate) is None
    assert formal_snapshot == (
        formal.canonical_peak_id,
        formal.canonical_version,
        formal.signal_type,
        formal.divergence_count,
        confirmed.confirm_date,
        confirmed.earliest_action_date,
        tracker.last_structural_peak,
        tracker.anchor,
        tracker.divergence_chain_id,
    )


@pytest.mark.parametrize(("increase", "reset"), [(1.999, False), (2.0, True)])
def test_same_canonical_update_obeys_anchor_reset_tolerance(
    increase: float, reset: bool
) -> None:
    tracker = DivergenceTracker()
    tracker.process(tracker_peak(0, 0, 100, 99, 80.0))
    chain_id = tracker.divergence_chain_id
    update = replace(
        tracker_peak(1, 2, 101, 100, 80.0 + increase),
        is_independent_peak=False,
        merged_into_peak_id="P0000",
        canonical_peak_id="P0000",
        representative_candidate_id="P0001",
        canonical_updated=True,
        canonical_version=2,
    )
    result = tracker.process(update)
    assert (result is not None) is reset
    if reset:
        assert result.reset_reason == "ANCHOR_RSI_BREAKOUT"
        assert result.same_canonical_anchor_breakout
        assert result.signal_type == SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE
        assert not result.position_eligible
        assert tracker.anchor.peak_rsi == 82.0
        assert tracker.anchor.representative_candidate_id == "P0001"
        assert tracker.last_structural_peak.representative_candidate_id == "P0001"
        assert tracker.divergence_chain_id != chain_id
        processed_chain = tracker.divergence_chain_id
        assert tracker.process(update) is None
        assert tracker.divergence_chain_id == processed_chain
    else:
        assert tracker.anchor.peak_rsi == 80.0
        assert tracker.anchor.representative_candidate_id == "P0000"
        assert tracker.last_structural_peak.representative_candidate_id == "P0000"
        assert tracker.divergence_chain_id == chain_id
    assert tracker.divergence_count == 0
