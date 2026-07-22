from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

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
    tracker.process(update)
    assert snapshot == (
        saved.canonical_peak_id,
        saved.canonical_version,
        saved.divergence_count,
        saved.previous_peak_date,
    )
