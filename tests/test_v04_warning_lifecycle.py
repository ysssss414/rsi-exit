from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.models import (
    SignalType,
    WarningEndReason,
    WarningLifecycleEvent,
    WarningPositionEffect,
    WarningSourceKind,
    WarningStatus,
)
from rsi_exit.pipeline import analyze_bars
from rsi_exit.release_check import load_frozen_bars as load_required_bars
from rsi_exit.warning_events import (
    WarningLifecycleContractError,
    WarningTracker,
    build_warning_events,
    build_warning_lifecycle_events,
    derive_warning_states,
    warning_events_frame,
)


PRIVATE_REGRESSION_BASELINE = (
    Path(__file__).parents[1]
    / "outputs"
    / "v0.2.1_baseline"
    / "300308.SZ_v0.2.1_frozen_baseline.zip"
)


def forming_source(
    *,
    peak_id: str = "FPK0001",
    version: int = 1,
    decision_date: str = "2026-01-05",
    peak_date: str | None = None,
    close: float = 100.0,
    rsi: float = 70.0,
    **overrides: object,
) -> dict[str, object]:
    source: dict[str, object] = {
        "signal_type": SignalType.DIVERGENCE_FORMING.value,
        "signal_status": "FORMING",
        "price_relation": "STRICT_NEW_HIGH",
        "candidate_peak_id": peak_id,
        "canonical_version": version,
        "current_peak_date": peak_date or decision_date,
        "current_peak_close": close,
        "current_peak_rsi": rsi,
        "decision_date": decision_date,
        "momentum_anchor_canonical_id": "P0001",
        "momentum_anchor_canonical_version": 2,
        "previous_canonical_peak_id": "P0002",
        "previous_canonical_version": 3,
        "divergence_chain_id": "DCHAIN0004",
        "risk_cycle_id": "CYCLE0005",
        "local_rsi_delta": -3.0,
        "anchor_rsi_delta": -5.0,
        "structural_eligible": False,
        "position_eligible": False,
        "pending_action_type": None,
        "is_warmup": False,
        "is_display_range": True,
        "latest_confirmed_canonical_id": "P0003",
        "latest_confirmed_canonical_version": 1,
    }
    source.update(overrides)
    return source


def formal_source(
    *,
    decision_date: str = "2026-01-06",
    peak_date: str = "2026-01-05",
    signal_type: str = SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
    current_canonical_id: str = "PK0008",
    current_canonical_version: int = 1,
    **overrides: object,
) -> dict[str, object]:
    source: dict[str, object] = {
        "symbol": "TEST.SZ",
        "decision_date": decision_date,
        "signal_type": signal_type,
        "signal_status": "FORMAL",
        "structural_eligible": True,
        "current_peak_date": peak_date,
        "current_canonical_peak_id": current_canonical_id,
        "current_canonical_version": current_canonical_version,
        "previous_canonical_peak_id": "P0002",
        "previous_canonical_version": 3,
        "momentum_anchor_canonical_id": "P0001",
        "momentum_anchor_canonical_version": 2,
        "divergence_chain_id": "DCHAIN0004",
        "position_eligible": False,
        "reset_reason": None,
        "same_canonical_anchor_breakout": False,
        "is_warmup": False,
        "is_display_range": True,
        "latest_confirmed_canonical_id": current_canonical_id,
        "latest_confirmed_canonical_version": current_canonical_version,
    }
    source.update(overrides)
    return source


def daily_source(
    date: str,
    *,
    close: object = 99.0,
    rsi: object = 69.0,
    **overrides: object,
) -> dict[str, object]:
    source: dict[str, object] = {
        "symbol": "TEST.SZ",
        "date": date,
        "close": close,
        "rsi": rsi,
        "is_warmup": False,
        "is_display_range": True,
    }
    source.update(overrides)
    return source


def build_lifecycle(
    *,
    forming: list[dict[str, object]],
    formal: list[dict[str, object]] | None = None,
    daily: list[dict[str, object]] | None = None,
) -> list:
    return build_warning_lifecycle_events(
        symbol="TEST.SZ",
        forming_sources=forming,
        formal_sources=formal or [],
        daily_sources=daily or [],
        deep_reset_rsi_level=50.0,
        deep_reset_consecutive_days=3,
        extreme_reset_rsi_level=40.0,
    )


@pytest.mark.parametrize("signal_type", [
    SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
    SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
])
@pytest.mark.parametrize("position_eligible", [True, False])
def test_unique_formal_divergence_escalates_without_position_dependency(
    signal_type: str,
    position_eligible: bool,
) -> None:
    events = build_lifecycle(
        forming=[forming_source()],
        formal=[formal_source(
            signal_type=signal_type,
            position_eligible=position_eligible,
        )],
    )
    opened, escalated = events
    assert opened.lifecycle_event == WarningLifecycleEvent.OPENED
    assert opened.source_canonical_peak_id is None
    assert escalated.lifecycle_event == WarningLifecycleEvent.ESCALATED
    assert escalated.warning_status == WarningStatus.ESCALATED
    assert escalated.source_kind == WarningSourceKind.FORMAL_SIGNAL
    assert escalated.end_reason == WarningEndReason.FORMAL_DIVERGENCE_CONFIRMED.value
    assert (escalated.source_canonical_peak_id, escalated.source_canonical_version) == (
        "PK0008", 1,
    )
    assert escalated.linked_formal_signal_ref == (
        f"TEST.SZ|{signal_type}|PK0008@v1|2026-01-06|DCHAIN0004"
    )
    evidence = json.loads(escalated.warning_evidence)
    assert evidence["formal_signal_ref"] == escalated.linked_formal_signal_ref
    assert escalated.position_effect == WarningPositionEffect.NONE
    assert escalated.recommended_position_cap is None


@pytest.mark.parametrize(("change", "value"), [
    ("symbol", "OTHER.SZ"),
    ("current_peak_date", "2026-01-04"),
    ("previous_canonical_peak_id", "OTHER"),
    ("previous_canonical_version", 4),
    ("momentum_anchor_canonical_id", "OTHER"),
    ("momentum_anchor_canonical_version", 3),
    ("divergence_chain_id", "OTHER"),
    ("decision_date", "2026-01-05"),
    ("signal_status", "FORMING"),
    ("structural_eligible", False),
])
def test_formal_matcher_mismatches_do_not_escalate(
    change: str,
    value: object,
) -> None:
    events = build_lifecycle(
        forming=[forming_source()],
        formal=[formal_source(**{change: value})],
    )
    assert [event.lifecycle_event for event in events] == [
        WarningLifecycleEvent.OPENED
    ]
    assert derive_warning_states(events) == {
        events[0].warning_id: WarningStatus.ACTIVE
    }


def test_multiple_formals_matching_one_warning_raise_contract_error() -> None:
    formals = [
        formal_source(current_canonical_id="PK0008"),
        formal_source(
            signal_type=SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
            current_canonical_id="PK0009",
        ),
    ]
    with pytest.raises(WarningLifecycleContractError, match="multiple formal"):
        build_lifecycle(forming=[forming_source()], formal=formals)


def test_one_formal_matching_multiple_warnings_raises_contract_error() -> None:
    forming = [
        forming_source(peak_id="FPK0001"),
        forming_source(peak_id="FPK0002"),
    ]
    with pytest.raises(WarningLifecycleContractError, match="multiple active warnings"):
        build_lifecycle(forming=forming, formal=[formal_source()])


def test_anchor_breakout_clears_only_latest_lineage() -> None:
    breakout = formal_source(
        signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
        reset_reason="ANCHOR_RSI_BREAKOUT",
        same_canonical_anchor_breakout=True,
    )
    events = build_lifecycle(forming=[forming_source()], formal=[breakout])
    cleared = events[-1]
    assert cleared.lifecycle_event == WarningLifecycleEvent.CLEARED
    assert cleared.warning_status == WarningStatus.CLEARED
    assert cleared.source_kind == WarningSourceKind.FORMAL_SIGNAL
    assert cleared.end_reason == WarningEndReason.MOMENTUM_ANCHOR_REBUILT.value
    assert cleared.linked_formal_signal_ref is None
    assert cleared.source_canonical_peak_id == "PK0008"
    assert json.loads(cleared.warning_evidence)["reset_reason"] == (
        "ANCHOR_RSI_BREAKOUT"
    )


def test_anchor_breakout_uses_new_anchor_and_chain_context() -> None:
    breakout = formal_source(
        signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
        reset_reason="ANCHOR_RSI_BREAKOUT",
        same_canonical_anchor_breakout=True,
        momentum_anchor_canonical_id="NEW_ANCHOR",
        momentum_anchor_canonical_version=1,
        divergence_chain_id="NEW_CHAIN",
    )
    events = build_lifecycle(forming=[forming_source()], formal=[breakout])
    assert events[-1].lifecycle_event == WarningLifecycleEvent.CLEARED


@pytest.mark.parametrize("overrides", [
    {"latest_confirmed_canonical_id": "OLD"},
    {"latest_confirmed_canonical_version": 2},
    {"reset_reason": None},
    {"structural_eligible": False},
    {"current_peak_date": "2026-01-04"},
])
def test_invalid_or_old_lineage_breakout_does_not_clear(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "signal_type": SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
        "reset_reason": "ANCHOR_RSI_BREAKOUT",
        "same_canonical_anchor_breakout": True,
    }
    values.update(overrides)
    fact = formal_source(**values)
    events = build_lifecycle(forming=[forming_source()], formal=[fact])
    assert events[-1].warning_status == WarningStatus.ACTIVE


@pytest.mark.parametrize(("values", "expected_date"), [
    ([49.0, 49.0, 49.0], "2026-01-08"),
    ([40.0], "2026-01-06"),
    ([39.9], "2026-01-06"),
])
def test_deep_reset_invalidates_on_strict_completion(
    values: list[float],
    expected_date: str,
) -> None:
    daily = [
        daily_source(
            date.strftime("%Y-%m-%d"),
            close=None,
            rsi=value,
        )
        for date, value in zip(
            pd.bdate_range("2026-01-06", periods=len(values)),
            values,
        )
    ]
    events = build_lifecycle(forming=[forming_source()], daily=daily)
    invalidated = events[-1]
    assert invalidated.lifecycle_event == WarningLifecycleEvent.INVALIDATED
    assert invalidated.warning_status == WarningStatus.INVALIDATED
    assert invalidated.source_kind == WarningSourceKind.DAILY_RSI
    assert invalidated.end_reason == WarningEndReason.DEEP_RSI_RESET_COMPLETED.value
    assert invalidated.decision_date == expected_date
    assert invalidated.linked_formal_signal_ref is None


@pytest.mark.parametrize("values", [
    [49.0],
    [49.0, 50.0, 49.0],
    [49.0, np.nan, 49.0, 49.0],
    [40.1],
])
def test_incomplete_deep_reset_remains_active(values: list[float]) -> None:
    daily = [
        daily_source(
            date.strftime("%Y-%m-%d"),
            close=None,
            rsi=value,
        )
        for date, value in zip(
            pd.bdate_range("2026-01-06", periods=len(values)),
            values,
        )
    ]
    events = build_lifecycle(forming=[forming_source()], daily=daily)
    assert events[-1].warning_status == WarningStatus.ACTIVE


def test_higher_forming_version_refreshes_before_daily_break() -> None:
    events = build_lifecycle(
        forming=[
            forming_source(),
            forming_source(
                version=2,
                decision_date="2026-01-06",
                close=101.0,
                rsi=71.0,
            ),
        ],
        daily=[daily_source("2026-01-06", close=98.0, rsi=68.0)],
    )
    assert [event.lifecycle_event for event in events] == [
        WarningLifecycleEvent.OPENED,
        WarningLifecycleEvent.REFRESHED,
    ]


@pytest.mark.parametrize(("signal_type", "reason"), [
    (
        SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
        WarningEndReason.CONFIRMED_WITHOUT_FORMAL_DIVERGENCE,
    ),
    (
        SignalType.INTRADAY_POTENTIAL_RETEST.value,
        WarningEndReason.INTRADAY_RETEST_ONLY,
    ),
    (
        SignalType.NON_COMPARABLE_PEAK.value,
        WarningEndReason.NON_COMPARABLE_CONFIRMATION,
    ),
])
def test_down_down_confirmation_invalidates_with_specific_reason(
    signal_type: str,
    reason: WarningEndReason,
) -> None:
    events = build_lifecycle(
        forming=[forming_source()],
        formal=[formal_source(
            signal_type=signal_type,
            structural_eligible=(
                signal_type
                == SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value
            ),
        )],
        daily=[daily_source("2026-01-06", close=99.0, rsi=69.0)],
    )
    invalidated = events[-1]
    assert invalidated.lifecycle_event == WarningLifecycleEvent.INVALIDATED
    assert invalidated.source_kind == WarningSourceKind.FORMAL_SIGNAL
    assert invalidated.end_reason == reason.value
    evidence = json.loads(invalidated.warning_evidence)
    assert evidence["matching_confirmation_type"] == signal_type


@pytest.mark.parametrize(("close", "rsi"), [
    (101.0, 69.0),
    (99.0, 71.0),
    (100.0, 69.0),
    (99.0, 70.0),
    (99.0, 69.0),
])
def test_determinable_broken_forming_invalidates_generically(
    close: float,
    rsi: float,
) -> None:
    events = build_lifecycle(
        forming=[forming_source()],
        daily=[daily_source("2026-01-06", close=close, rsi=rsi)],
    )
    invalidated = events[-1]
    assert invalidated.lifecycle_event == WarningLifecycleEvent.INVALIDATED
    assert invalidated.end_reason == WarningEndReason.FORMING_CONDITION_BROKEN.value
    assert invalidated.source_kind == WarningSourceKind.DAILY_RSI


@pytest.mark.parametrize(("close", "rsi"), [
    (None, 69.0),
    (99.0, None),
    (np.nan, 69.0),
    (99.0, np.nan),
])
def test_missing_daily_comparison_keeps_warning_active(
    close: object,
    rsi: object,
) -> None:
    events = build_lifecycle(
        forming=[forming_source()],
        daily=[daily_source("2026-01-06", close=close, rsi=rsi)],
    )
    assert events[-1].warning_status == WarningStatus.ACTIVE


def test_same_day_priority_escalated_over_cleared() -> None:
    divergence = formal_source()
    breakout = formal_source(
        signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
        current_canonical_id="PK0009",
        reset_reason="ANCHOR_RSI_BREAKOUT",
        same_canonical_anchor_breakout=True,
    )
    events = build_lifecycle(
        forming=[forming_source()], formal=[breakout, divergence]
    )
    assert events[-1].lifecycle_event == WarningLifecycleEvent.ESCALATED


def test_same_day_priority_cleared_over_refreshed() -> None:
    events = build_lifecycle(
        forming=[
            forming_source(),
            forming_source(version=2, decision_date="2026-01-06"),
        ],
        formal=[formal_source(
            signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
            reset_reason="ANCHOR_RSI_BREAKOUT",
            same_canonical_anchor_breakout=True,
        )],
    )
    assert events[-1].lifecycle_event == WarningLifecycleEvent.CLEARED
    assert len(events) == 2


@pytest.mark.parametrize("daily", [
    [daily_source("2026-01-06", close=None, rsi=40.0)],
    [daily_source("2026-01-06", close=99.0, rsi=69.0)],
])
def test_same_day_priority_refreshed_over_invalidation(
    daily: list[dict[str, object]],
) -> None:
    events = build_lifecycle(
        forming=[
            forming_source(),
            forming_source(version=2, decision_date="2026-01-06"),
        ],
        daily=daily,
    )
    assert events[-1].lifecycle_event == WarningLifecycleEvent.REFRESHED


@pytest.mark.parametrize("terminal", ["ESCALATED", "CLEARED", "INVALIDATED"])
def test_terminal_warning_cannot_revive_or_terminate_twice(terminal: str) -> None:
    forming = [
        forming_source(),
        forming_source(version=2, decision_date="2026-01-07"),
    ]
    formal: list[dict[str, object]] = []
    daily: list[dict[str, object]] = []
    if terminal == "ESCALATED":
        fact = formal_source()
        formal = [fact, deepcopy(fact)]
    elif terminal == "CLEARED":
        fact = formal_source(
            signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
            reset_reason="ANCHOR_RSI_BREAKOUT",
            same_canonical_anchor_breakout=True,
        )
        formal = [fact, deepcopy(fact)]
    else:
        daily = [
            daily_source("2026-01-06", close=None, rsi=40.0),
            daily_source("2026-01-07", close=None, rsi=39.0),
        ]
    events = build_lifecycle(forming=forming, formal=formal, daily=daily)
    assert len(events) == 2
    assert events[-1].warning_status.value == terminal


@pytest.mark.parametrize("terminal", ["ESCALATED", "CLEARED", "INVALIDATED"])
def test_prefix_events_equal_full_history_prefix(terminal: str) -> None:
    forming = [
        forming_source(),
        forming_source(version=2, decision_date="2026-01-06"),
    ]
    formal: list[dict[str, object]] = []
    daily = [daily_source("2026-01-06", close=101.0, rsi=71.0)]
    if terminal == "ESCALATED":
        formal = [formal_source(decision_date="2026-01-07", peak_date="2026-01-06")]
    elif terminal == "CLEARED":
        formal = [formal_source(
            decision_date="2026-01-07",
            peak_date="2026-01-06",
            signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE.value,
            reset_reason="ANCHOR_RSI_BREAKOUT",
            same_canonical_anchor_breakout=True,
        )]
    else:
        daily.append(daily_source("2026-01-07", close=None, rsi=40.0))
    full = warning_events_frame(build_lifecycle(
        forming=forming,
        formal=formal,
        daily=daily,
    ))
    for cutoff in sorted(full["decision_date"].unique()):
        prefix = warning_events_frame(build_lifecycle(
            forming=[item for item in forming if item["decision_date"] <= cutoff],
            formal=[item for item in formal if item["decision_date"] <= cutoff],
            daily=[item for item in daily if item["date"] <= cutoff],
        ))
        expected = full.loc[full["decision_date"] <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix, expected)


def test_as_of_states_are_derived_only_from_event_history() -> None:
    escalated = build_lifecycle(
        forming=[
            forming_source(),
            forming_source(version=2, decision_date="2026-01-06"),
        ],
        formal=[formal_source(decision_date="2026-01-07", peak_date="2026-01-06")],
        daily=[daily_source("2026-01-06", close=101.0, rsi=71.0)],
    )
    warning_id = escalated[0].warning_id
    assert derive_warning_states(escalated, as_of_date="2026-01-05") == {
        warning_id: WarningStatus.ACTIVE
    }
    assert derive_warning_states(escalated, as_of_date="2026-01-06") == {
        warning_id: WarningStatus.ACTIVE
    }
    assert derive_warning_states(escalated, as_of_date="2026-01-07") == {
        warning_id: WarningStatus.ESCALATED
    }
    assert all(event.warning_status.value != "ACTIVE_AT_CUTOFF" for event in escalated)


def scripted_bars() -> tuple[pd.DataFrame, pd.Series]:
    count = 40
    index = np.arange(count)
    close = 90 + index * 0.02
    rsi = pd.Series(65.0, index=index)
    for peak_index, peak_close, peak_rsi in (
        (10, 100, 80), (16, 101, 77), (22, 102, 74), (28, 103, 71),
    ):
        close[peak_index - 1 : peak_index + 2] = [
            peak_close - 2, peak_close, peak_close - 3,
        ]
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


def test_pipeline_lifecycle_isolated_from_all_formal_outputs(monkeypatch) -> None:
    bars, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    normal = analyze_bars(bars, symbol="LIFECYCLE.TEST", config=load_config())

    def phase1_only(**kwargs):
        return build_warning_events(
            symbol=kwargs["symbol"],
            sources=kwargs["forming_sources"],
        )

    monkeypatch.setattr(
        "rsi_exit.pipeline.build_warning_lifecycle_events",
        phase1_only,
    )
    isolated = analyze_bars(bars, symbol="LIFECYCLE.TEST", config=load_config())
    for attribute in (
        "daily_features", "peaks", "canonical_peaks", "signals", "state_log",
        "cycle_log", "rsi_audit",
    ):
        pd.testing.assert_frame_equal(
            getattr(normal, attribute),
            getattr(isolated, attribute),
        )
    assert normal.warnings == isolated.warnings
    assert normal.metadata == isolated.metadata


def test_private_frozen_lifecycle_smoke_preserves_formal_outputs() -> None:
    if not PRIVATE_REGRESSION_BASELINE.exists():
        pytest.skip("private frozen regression input is unavailable")
    result = analyze_bars(
        load_required_bars(PRIVATE_REGRESSION_BASELINE),
        symbol="300308.SZ",
        name="中际旭创",
        config=load_config(),
        display_start_date="2026-05-01",
        display_end_date="2026-07-20",
    )
    formal_types = {
        SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
        SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
    }
    assert int(result.signals["signal_type"].isin(formal_types).sum()) == 3
    assert set(result.warning_events["position_effect"]) == {"NONE"}
    assert set(result.warning_events["lifecycle_event"]) <= {
        item.value for item in WarningLifecycleEvent
    }


def test_warning_tracker_is_independent_public_lifecycle_component() -> None:
    tracker = WarningTracker(symbol="TEST.SZ")
    assert tracker.symbol == "TEST.SZ"
    assert tracker.events == []
