from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from rsi_exit.config import RsiExitConfig, load_config
from rsi_exit.divergence import DivergenceTracker
from rsi_exit.models import CanonicalPeak, Peak, PeakEvent
from rsi_exit.peak_detector import PeakDetector
from rsi_exit.pipeline import analyze_bars
from rsi_exit.state_machine import RsiExitStateMachine


def _frame(close: list[float], rsi: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=len(close)),
        "close": close,
        "rsi14": rsi,
    })


def _bars(count: int = 150) -> pd.DataFrame:
    index = np.arange(count)
    close = 100 + index * 0.25 + np.sin(index / 4) * 2
    return pd.DataFrame({
        "date": pd.bdate_range("2025-01-01", periods=count),
        "open": close * 0.995,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1000 + index,
        "amount": close * (1000 + index),
    })


def test_default_peak_candidate_does_not_require_recent_window_max() -> None:
    source = _frame([10, 20, 15, 16, 15], [50, 90, 60, 70, 65])
    default, _ = PeakDetector().detect(source)
    strict, _ = PeakDetector(require_recent_window_max=True, lookback=3).detect(source)
    assert "2026-01-06" in default["peak_date"].tolist()
    assert "2026-01-06" not in strict["peak_date"].tolist()


def test_canonical_table_keeps_only_current_representative() -> None:
    detector = PeakDetector()
    candidates, _ = detector.detect(
        _frame([8, 9, 10, 9.5, 10.2, 9.8], [40, 50, 70, 60, 71, 65])
    )
    canonical = detector.canonical_peaks_frame()
    assert candidates["candidate_peak_id"].is_unique
    assert len(canonical) == 1
    assert canonical.iloc[0]["representative_candidate_id"] == "CP0002"
    assert canonical.iloc[0]["canonical_version"] == 2


def _event(candidate_id: str, canonical_id: str, version: int, rsi: float, close: float, *, created: bool, updated: bool) -> PeakEvent:
    date = pd.Timestamp("2026-01-01") + pd.offsets.BDay(int(candidate_id[-1]) * 4)
    peak = Peak(
        peak_id=candidate_id, candidate_peak_id=candidate_id,
        canonical_peak_id=canonical_id, representative_candidate_id=candidate_id,
        canonical_version=version, peak_index=int(candidate_id[-1]) * 4,
        peak_date=date, confirm_index=int(candidate_id[-1]) * 4 + 1,
        confirm_date=date + pd.offsets.BDay(1), earliest_action_date=date + pd.offsets.BDay(2),
        peak_close=close, peak_rsi=rsi, confirm_close=close - 1, confirm_rsi=rsi - 1,
        days_from_previous_peak=4, interim_min_close=close * .95, interim_min_rsi=60,
        price_retrace_pct=.05, rsi_retrace=5, is_independent_peak=created,
        merged_into_peak_id=None if created else canonical_id, previous_peak_id=None,
        canonical_updated=updated,
    )
    canonical = CanonicalPeak(
        canonical_peak_id=canonical_id, representative_candidate_id=candidate_id,
        canonical_version=version, peak_index=peak.peak_index, peak_date=peak.peak_date,
        confirm_index=peak.confirm_index, confirm_date=peak.confirm_date,
        earliest_action_date=peak.earliest_action_date, peak_close=close, peak_rsi=rsi,
        confirm_close=peak.confirm_close, confirm_rsi=peak.confirm_rsi,
        days_from_previous_peak=4, interim_min_close=peak.interim_min_close,
        interim_min_rsi=peak.interim_min_rsi, price_retrace_pct=.05, rsi_retrace=5,
        previous_canonical_peak_id=None,
    )
    return PeakEvent(peak, canonical, created, updated)


def test_merged_b_can_overtake_a_as_global_momentum_anchor() -> None:
    tracker = DivergenceTracker()
    tracker.process(_event("CP0001", "PK0001", 1, 80, 100, created=True, updated=False))
    tracker.process(_event("CP0002", "PK0002", 1, 75, 101, created=True, updated=False))
    assert tracker.anchor.canonical_peak_id == "PK0001"
    tracker.process(_event("CP0003", "PK0002", 2, 85, 102, created=False, updated=True))
    assert tracker.anchor.canonical_peak_id == "PK0002"
    assert tracker.anchor.representative_candidate_id == "CP0003"
    assert tracker.anchor.canonical_version == 2


def test_lower_rsi_same_canonical_update_never_lowers_anchor() -> None:
    tracker = DivergenceTracker()
    tracker.process(_event("CP0001", "PK0001", 1, 80, 100, created=True, updated=False))
    tracker.process(_event("CP0002", "PK0001", 2, 75, 110, created=False, updated=True))
    assert tracker.previous.representative_candidate_id == "CP0002"
    assert tracker.anchor.representative_candidate_id == "CP0001"
    assert tracker.anchor.peak_rsi == 80


def test_first_global_merge_after_reset_establishes_new_cycle_baseline() -> None:
    tracker = DivergenceTracker()
    tracker.process(_event("CP0001", "PK0001", 1, 80, 100, created=True, updated=False))
    tracker.reset_cycle("CYCLE0002")
    merged = _event("CP0002", "PK0001", 1, 78, 99, created=False, updated=False)
    assert tracker.process(merged) is None
    assert tracker.previous.representative_candidate_id == "CP0002"
    assert tracker.previous.peak_rsi == 78
    followup = tracker.process(_event("CP0003", "PK0002", 1, 75, 101, created=True, updated=False))
    assert followup is not None
    assert followup.previous_candidate_peak_id == "CP0002"
    assert followup.cycle_id == "CYCLE0002"


def test_warmup_is_computed_then_display_is_cropped() -> None:
    source = _bars()
    result = analyze_bars(
        source, symbol="300308.SZ", config=load_config(),
        display_start_date=source.iloc[120]["date"], display_end_date=source.iloc[-1]["date"],
    )
    assert result.metadata["warmup_satisfied"] is True
    assert result.metadata["warmup_trading_days_actual"] == 120
    assert result.metadata["warmup_rows"] == 120
    assert result.metadata["source_row_count"] == 150
    assert result.metadata["indicator_ready_on_display_start"] is True
    assert len(result.daily_features) == 30
    assert len(result.rsi_audit) == 150
    assert result.rsi_audit["is_warmup"].sum() == 120
    assert result.daily_features.iloc[0]["date"] == source.iloc[120]["date"].strftime("%Y-%m-%d")


def test_more_than_120_warmup_rows_stabilizes_same_display_rsi() -> None:
    source = _bars(170)
    display_start = source.iloc[140]["date"]
    longer = analyze_bars(
        source, symbol="300308.SZ", config=load_config(),
        display_start_date=display_start, display_end_date=source.iloc[-1]["date"],
    )
    exactly_120 = analyze_bars(
        source.iloc[20:].reset_index(drop=True), symbol="300308.SZ", config=load_config(),
        display_start_date=display_start, display_end_date=source.iloc[-1]["date"],
    )
    merged = longer.daily_features[["date", "rsi14"]].merge(
        exactly_120.daily_features[["date", "rsi14"]], on="date", suffixes=("_long", "_120")
    )
    assert (merged["rsi14_long"] - merged["rsi14_120"]).abs().max() < 0.01


def test_every_signal_identity_is_reconstructable_from_peak_outputs() -> None:
    source = _bars()
    result = analyze_bars(
        source, symbol="300308.SZ", config=load_config(),
        display_start_date=source.iloc[120]["date"], display_end_date=source.iloc[-1]["date"],
    )
    assert not result.signals.empty
    candidates = result.peaks.set_index("candidate_peak_id", verify_integrity=True)
    canonical_ids = set(result.canonical_peaks["canonical_peak_id"])
    formal = result.signals.loc[result.signals["signal_status"] == "FORMAL"]
    for _, signal in formal.iterrows():
        current = candidates.loc[signal["current_candidate_peak_id"]]
        previous = candidates.loc[signal["previous_candidate_peak_id"]]
        assert signal["current_canonical_peak_id"] in canonical_ids
        assert signal["previous_canonical_peak_id"] in canonical_ids
        assert current["peak_date"] == signal["current_peak_date"]
        assert current["peak_close"] == signal["current_peak_close"]
        assert current["peak_rsi"] == signal["current_peak_rsi"]
        assert previous["peak_date"] == signal["previous_peak_date"]
        assert previous["peak_close"] == signal["previous_peak_close"]
        assert previous["peak_rsi"] == signal["previous_peak_rsi"]


def test_base_decision_only_becomes_effective_next_trading_day() -> None:
    source = _bars()
    decision_index = 125
    source["hard_exit"] = 0
    source.loc[decision_index, "hard_exit"] = 1
    result = analyze_bars(
        source, symbol="300308.SZ", config=load_config(),
        display_start_date=source.iloc[120]["date"], display_end_date=source.iloc[-1]["date"],
    )
    decision_date = source.iloc[decision_index]["date"].strftime("%Y-%m-%d")
    next_date = source.iloc[decision_index + 1]["date"].strftime("%Y-%m-%d")
    decision = result.daily_features.set_index("date").loc[decision_date]
    effective = result.daily_features.set_index("date").loc[next_date]
    assert decision["decision_base_state"] == "S3_EXIT"
    assert decision["effective_base_state"] != "S3_EXIT"
    assert effective["effective_base_state"] == "S3_EXIT"


def test_configured_state_threshold_and_cap_are_used() -> None:
    cfg = load_config()
    values = deepcopy(cfg.values)
    values["levels"]["strong"] = 80.0
    values["position_caps"]["base_s2"] = 0.3
    custom = RsiExitConfig(values, cfg.source_path)
    machine = RsiExitStateMachine(
        levels=custom.values["levels"], position_caps=custom.values["position_caps"]
    )
    assert machine.step(rsi=75, close=110, ma20=100).current_state.value == "S1_STRONG_PULLBACK"
    assert machine.step(rsi=59, close=110, ma20=100).position_cap == 0.3


def test_full_reentry_then_normal_pullback_sequence() -> None:
    machine = RsiExitStateMachine()
    assert machine.step(rsi=49, close=90, ma20=100).current_state.value == "S3_EXIT"
    assert machine.step(rsi=65, close=110, ma20=100).current_state.value == "S4_REPAIR_WATCH"
    qualified = machine.step(
        rsi=72, close=110, ma20=100, decision_date=pd.Timestamp("2026-01-05")
    )
    assert qualified.current_state.value == "S0_MAIN_TREND"
    assert qualified.state_event == "ALLOW_REENTRY"
    assert qualified.reentry_qualification_date == pd.Timestamp("2026-01-05")
    assert machine.step(rsi=65, close=110, ma20=100).current_state.value == "S1_STRONG_PULLBACK"
    assert machine.step(rsi=59, close=110, ma20=100).current_state.value == "S2_RISK_DOWNGRADE"
    assert machine.step(rsi=58, close=110, ma20=100).current_state.value == "S3_EXIT"


def test_insufficient_history_starts_uninitialized_not_s0() -> None:
    source = _bars(10)
    result = analyze_bars(source, symbol="300308.SZ", config=load_config())
    assert result.daily_features.iloc[0]["decision_base_state"] == "UNINITIALIZED"
    assert result.daily_features.iloc[0]["effective_base_state"] == "UNINITIALIZED"
    assert any(item.startswith("HIGH_PRIORITY") for item in result.warnings)


def test_prefix_causality_keeps_confirmed_candidate_identity() -> None:
    source = _frame([10, 11, 12, 11, 13, 12, 14, 13], [50, 60, 70, 65, 75, 70, 80, 75])
    prefix, _ = PeakDetector().detect(source.iloc[:6], trading_calendar=source["date"])
    full, _ = PeakDetector().detect(source, trading_calendar=source["date"])
    pd.testing.assert_frame_equal(
        prefix.reset_index(drop=True),
        full.iloc[: len(prefix)].reset_index(drop=True),
    )
