from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import AnalysisResult, analyze_bars
from rsi_exit.plotting import (
    _select_warning_lifecycle_events,
    _warning_lifecycle_plot_points,
    create_annotated_chart,
)
from rsi_exit.release_check import load_frozen_bars
from rsi_exit.reporting import _warning_reporting_snapshot, build_summary
from rsi_exit.warning_events import WARNING_EVENT_COLUMNS


PRIVATE_REGRESSION_BASELINE = (
    Path(__file__).parents[1]
    / "outputs"
    / "v0.2.1_baseline"
    / "300308.SZ_v0.2.1_frozen_baseline.zip"
)


def warning_event(
    warning_id: str,
    lifecycle_event: str,
    decision_date: str,
    *,
    version: int = 1,
    source_peak_date: str = "2026-01-04",
    is_warmup: bool = False,
    formal_ref: str | None = None,
) -> dict[str, object]:
    status = (
        "ACTIVE"
        if lifecycle_event in {"OPENED", "REFRESHED"}
        else lifecycle_event
    )
    source_kind = (
        "FORMING_PEAK"
        if lifecycle_event in {"OPENED", "REFRESHED"}
        else "DAILY_RSI"
        if lifecycle_event == "INVALIDATED"
        else "FORMAL_SIGNAL"
    )
    end_reasons = {
        "ESCALATED": "FORMAL_DIVERGENCE_CONFIRMED",
        "CLEARED": "MOMENTUM_ANCHOR_REBUILT",
        "INVALIDATED": "FORMING_CONDITION_BROKEN",
    }
    row: dict[str, object] = {
        column: None for column in WARNING_EVENT_COLUMNS
    }
    row.update({
        "symbol": "TEST.SZ",
        "warning_event_id": (
            f"{warning_id}-{lifecycle_event}-{decision_date}-v{version}"
        ),
        "warning_id": warning_id,
        "warning_type": "FORMING_DIVERGENCE_WARNING",
        "lifecycle_event": lifecycle_event,
        "warning_status": status,
        "source_kind": source_kind,
        "source_peak_id": f"FPK-{warning_id}",
        "source_version": version,
        "source_peak_date": source_peak_date,
        "observation_date": decision_date,
        "decision_date": decision_date,
        "available_date": decision_date,
        "momentum_anchor_id": "P0001",
        "momentum_anchor_version": 1,
        "last_structural_peak_id": "P0002",
        "last_structural_peak_version": 1,
        "divergence_chain_id": f"CHAIN-{warning_id}",
        "risk_cycle_id": f"CYCLE-{warning_id}",
        "price_relation": "STRICT_NEW_HIGH",
        "local_rsi_delta": -2.25,
        "anchor_rsi_delta": -3.5,
        "warning_reason": f"FORMING_DIVERGENCE_{lifecycle_event}",
        "warning_evidence": "{}",
        "end_reason": end_reasons.get(lifecycle_event),
        "linked_formal_signal_ref": formal_ref,
        "position_effect": "NONE",
        "recommended_position_cap": None,
        "is_warmup": is_warmup,
        "is_display_range": not is_warmup,
    })
    return row


def warning_frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=WARNING_EVENT_COLUMNS)


def result_with_warnings(
    events: pd.DataFrame,
    *,
    display_start: str = "2026-01-05",
    display_end: str = "2026-01-10",
    missing_rsi_date: str | None = None,
) -> AnalysisResult:
    dates = pd.date_range("2026-01-02", "2026-01-12", freq="D")
    rsi = np.linspace(65.0, 73.0, len(dates))
    if missing_rsi_date is not None:
        rsi[dates == pd.Timestamp(missing_rsi_date)] = np.nan
    daily = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "close": np.linspace(100.0, 108.0, len(dates)),
        "ma": np.linspace(99.0, 107.0, len(dates)),
        "rsi": rsi,
        "decision_base_state": "S0_MAIN_TREND",
        "effective_base_state": "S0_MAIN_TREND",
        "effective_final_position_cap": 1.0,
    })
    metadata = {
        "calculation_start_date": "2026-01-02",
        "calculation_end_date": "2026-01-12",
        "display_start_date": display_start,
        "display_end_date": display_end,
        "warmup_trading_days_requested": 120,
        "warmup_trading_days_actual": 120,
        "warmup_satisfied": True,
        "source": "synthetic",
        "adjust": "forward",
        "input_checksum_sha256": "TEST-CHECKSUM",
        "rsi_algorithm": "CN SMA",
        "seed_mode": "first",
        "rsi_difference_explanation": "synthetic test",
        "ma_period": 20,
        "rsi_period": 14,
        "rsi_levels": {
            "strong": 80.0,
            "life": 70.0,
            "neutral": 50.0,
            "weak": 30.0,
        },
        "config_version": "0.3.0",
    }
    return AnalysisResult(
        symbol="TEST.SZ",
        name="Test",
        daily_features=daily,
        peaks=pd.DataFrame(),
        canonical_peaks=pd.DataFrame(),
        signals=pd.DataFrame(columns=["signal_type", "is_display_range"]),
        state_log=pd.DataFrame(),
        cycle_log=pd.DataFrame(),
        rsi_audit=pd.DataFrame(),
        warnings=["synthetic system warning"],
        metadata=metadata,
        warning_events=events,
    )


def lifecycle_fixture() -> pd.DataFrame:
    return warning_frame(
        warning_event("W-ACTIVE", "OPENED", "2026-01-05"),
        warning_event("W-REFRESH", "OPENED", "2026-01-05"),
        warning_event("W-REFRESH", "REFRESHED", "2026-01-06", version=2),
        warning_event("W-ESC", "OPENED", "2026-01-05"),
        warning_event(
            "W-ESC",
            "ESCALATED",
            "2026-01-07",
            formal_ref="TEST.SZ|NEW_HIGH_BEARISH_DIVERGENCE|PK9@v1|2026-01-07|CHAIN-W-ESC",
        ),
        warning_event("W-CLEAR", "OPENED", "2026-01-05"),
        warning_event("W-CLEAR", "CLEARED", "2026-01-08"),
        warning_event("W-INVALID", "OPENED", "2026-01-05"),
        warning_event("W-INVALID", "INVALIDATED", "2026-01-09"),
    )


def test_summary_reports_warning_states_and_timeline_in_fixed_order() -> None:
    events = lifecycle_fixture()
    result = result_with_warnings(events)
    snapshot = _warning_reporting_snapshot(
        events,
        display_start_date="2026-01-05",
        display_end_date="2026-01-10",
    )
    assert snapshot["state_counts"] == {
        "ACTIVE": 2,
        "ESCALATED": 1,
        "CLEARED": 1,
        "INVALIDATED": 1,
    }
    assert snapshot["event_counts"] == {
        "OPENED": 5,
        "REFRESHED": 1,
        "ESCALATED": 1,
        "CLEARED": 1,
        "INVALIDATED": 1,
    }
    assert snapshot["active"]["warning_id"].tolist() == [
        "W-ACTIVE", "W-REFRESH",
    ]
    assert snapshot["timeline"].loc[
        snapshot["timeline"]["decision_date"] == "2026-01-05",
        "warning_id",
    ].tolist() == [
        "W-ACTIVE", "W-CLEAR", "W-ESC", "W-INVALID", "W-REFRESH",
    ]

    summary = build_summary(result, load_config())
    assert (
        "- 当前预警状态：ACTIVE 2 / ESCALATED 1 / CLEARED 1 / "
        "INVALIDATED 1"
    ) in summary
    assert (
        "- 展示区间事件：OPENED 5 / REFRESHED 1 / ESCALATED 1 / "
        "CLEARED 1 / INVALIDATED 1"
    ) in summary
    assert "local_rsi_delta=-2.25" in summary
    assert "anchor_rsi_delta=-3.50" in summary
    assert summary.index("## 信号与仓位") < summary.index(
        "## 背离预警生命周期"
    ) < summary.index("## RSI口径审计")
    assert "## 警告" in summary


def test_summary_cutoff_does_not_leak_future_terminal_event() -> None:
    events = warning_frame(
        warning_event("W-CUTOFF", "OPENED", "2026-01-05"),
        warning_event(
            "W-CUTOFF",
            "ESCALATED",
            "2026-01-11",
            formal_ref="FUTURE-FORMAL-REF",
        ),
    )
    summary = build_summary(result_with_warnings(events), load_config())
    assert (
        "当前预警状态：ACTIVE 1 / ESCALATED 0 / CLEARED 0 / INVALIDATED 0"
        in summary
    )
    assert "FUTURE-FORMAL-REF" not in summary
    assert "ACTIVE_AT_CUTOFF" not in summary


def test_warmup_active_warning_is_current_but_not_in_display_timeline() -> None:
    events = warning_frame(warning_event(
        "W-WARMUP",
        "OPENED",
        "2026-01-03",
        is_warmup=True,
    ))
    summary = build_summary(result_with_warnings(events), load_config())
    active_section, timeline = summary.split(
        "### 展示区间生命周期事件", maxsplit=1
    )
    assert "W-WARMUP" in active_section
    assert "W-WARMUP" not in timeline
    assert "展示区间事件：OPENED 0" in summary


def test_event_counts_remain_separate_from_warning_state_counts() -> None:
    events = warning_frame(
        warning_event("W-ONE", "OPENED", "2026-01-05"),
        warning_event("W-ONE", "REFRESHED", "2026-01-06", version=2),
        warning_event("W-ONE", "REFRESHED", "2026-01-07", version=3),
        warning_event("W-ONE", "INVALIDATED", "2026-01-08", version=3),
    )
    summary = build_summary(result_with_warnings(events), load_config())
    assert (
        "当前预警状态：ACTIVE 0 / ESCALATED 0 / CLEARED 0 / INVALIDATED 1"
        in summary
    )
    assert (
        "展示区间事件：OPENED 1 / REFRESHED 2 / ESCALATED 0 / "
        "CLEARED 0 / INVALIDATED 1"
    ) in summary


def test_empty_warning_events_render_summary_and_chart(tmp_path: Path) -> None:
    result = result_with_warnings(pd.DataFrame())
    summary = build_summary(result, load_config())
    assert (
        "当前预警状态：ACTIVE 0 / ESCALATED 0 / CLEARED 0 / INVALIDATED 0"
        in summary
    )
    assert (
        "展示区间事件：OPENED 0 / REFRESHED 0 / ESCALATED 0 / "
        "CLEARED 0 / INVALIDATED 0"
    ) in summary
    warning_section = summary.split("## 背离预警生命周期", maxsplit=1)[1]
    assert warning_section.count("- 无。") >= 2
    output = create_annotated_chart(
        result,
        tmp_path / "empty-warning-chart.png",
        config=load_config(),
    )
    assert output.is_file()


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (True, ["OPENED", "ESCALATED"]),
        (False, ["OPENED", "REFRESHED"]),
    ],
)
def test_chart_selects_opened_and_latest_event_only(
    terminal: bool,
    expected: list[str],
) -> None:
    rows = [
        warning_event("W-PLOT", "OPENED", "2026-01-05"),
        warning_event("W-PLOT", "REFRESHED", "2026-01-06", version=2),
        warning_event("W-PLOT", "REFRESHED", "2026-01-07", version=3),
    ]
    if terminal:
        rows.append(warning_event(
            "W-PLOT", "ESCALATED", "2026-01-08", version=3
        ))
    selected = _select_warning_lifecycle_events(
        warning_frame(*rows),
        display_start_date="2026-01-05",
        display_end_date="2026-01-10",
    )
    assert selected["lifecycle_event"].tolist() == expected


def test_chart_does_not_move_warmup_open_to_display_start() -> None:
    opened = warning_event(
        "W-WARM-PLOT",
        "OPENED",
        "2026-01-03",
        is_warmup=True,
    )
    assert _select_warning_lifecycle_events(
        warning_frame(opened),
        display_start_date="2026-01-05",
        display_end_date="2026-01-10",
    ).empty

    selected = _select_warning_lifecycle_events(
        warning_frame(
            opened,
            warning_event(
                "W-WARM-PLOT",
                "INVALIDATED",
                "2026-01-08",
            ),
        ),
        display_start_date="2026-01-05",
        display_end_date="2026-01-10",
    )
    assert selected["lifecycle_event"].tolist() == ["INVALIDATED"]
    assert selected["decision_date"].tolist() == ["2026-01-08"]


def test_missing_daily_rsi_skips_warning_point_without_substitution(
    tmp_path: Path,
) -> None:
    events = warning_frame(warning_event(
        "W-MISSING",
        "OPENED",
        "2026-01-05",
    ))
    result = result_with_warnings(events, missing_rsi_date="2026-01-05")
    points = _warning_lifecycle_plot_points(
        events,
        result.daily_features,
        display_start_date="2026-01-05",
        display_end_date="2026-01-10",
    )
    assert points.empty
    output = create_annotated_chart(
        result,
        tmp_path / "missing-rsi-chart.png",
        config=load_config(),
    )
    assert output.is_file()


def test_reporting_and_chart_do_not_modify_analysis_outputs(
    tmp_path: Path,
) -> None:
    result = result_with_warnings(lifecycle_fixture())
    frames = (
        "daily_features", "peaks", "canonical_peaks", "signals", "state_log",
        "cycle_log", "rsi_audit", "warning_events",
    )
    before = {name: getattr(result, name).copy(deep=True) for name in frames}
    warnings_before = deepcopy(result.warnings)
    metadata_before = deepcopy(result.metadata)

    build_summary(result, load_config())
    create_annotated_chart(
        result,
        tmp_path / "immutability-chart.png",
        config=load_config(),
    )

    for name in frames:
        pd.testing.assert_frame_equal(getattr(result, name), before[name])
    assert result.warnings == warnings_before
    assert result.metadata == metadata_before
    assert result.warning_events.columns.tolist() == WARNING_EVENT_COLUMNS
    assert set(result.warning_events["position_effect"]) == {"NONE"}
    assert result.warning_events["recommended_position_cap"].isna().all()


def test_private_frozen_warning_reporting_smoke(tmp_path: Path) -> None:
    if not PRIVATE_REGRESSION_BASELINE.exists():
        pytest.skip("private frozen regression input is unavailable")
    result = analyze_bars(
        load_frozen_bars(PRIVATE_REGRESSION_BASELINE),
        symbol="300308.SZ",
        name="中际旭创",
        config=load_config(),
        display_start_date="2026-05-01",
        display_end_date="2026-07-20",
    )
    summary = build_summary(result, load_config())
    assert (
        "当前预警状态：ACTIVE 0 / ESCALATED 3 / CLEARED 0 / INVALIDATED 4"
        in summary
    )
    assert (
        "展示区间事件：OPENED 4 / REFRESHED 8 / ESCALATED 3 / "
        "CLEARED 0 / INVALIDATED 1"
    ) in summary
    output = create_annotated_chart(
        result,
        tmp_path / "frozen-warning-chart.png",
        config=load_config(),
    )
    assert output.is_file()
    formal_types = {
        SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
        SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
    }
    assert int(result.signals["signal_type"].isin(formal_types).sum()) == 3
