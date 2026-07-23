from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import AnalysisResult, analyze_bars
from rsi_exit.release_check import load_frozen_bars
from rsi_exit.reporting import _warning_reporting_snapshot
from rsi_exit.validation import (
    HORIZONS,
    build_validation_bundle,
    validate_sample_result,
)
from rsi_exit.warning_events import WARNING_EVENT_COLUMNS


SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "run_v04_phase4_validation.py"
)
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "run_v04_phase4_validation", SCRIPT_PATH
)
if SCRIPT_SPEC is None or SCRIPT_SPEC.loader is None:
    raise ImportError(f"cannot load Phase 4 validation script: {SCRIPT_PATH}")
run_v04_phase4_validation = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(run_v04_phase4_validation)

PRIVATE_REGRESSION_BASELINE = (
    Path(__file__).parents[1]
    / "outputs"
    / "v0.2.1_baseline"
    / "300308.SZ_v0.2.1_frozen_baseline.zip"
)


def _event(
    warning_id: str,
    lifecycle_event: str,
    decision_date: str,
    *,
    version: int = 1,
    status: str | None = None,
    end_reason: str | None = None,
    linked_formal_signal_ref: str | None = None,
) -> dict[str, object]:
    terminal_statuses = {"ESCALATED", "CLEARED", "INVALIDATED"}
    row = {column: None for column in WARNING_EVENT_COLUMNS}
    row.update({
        "symbol": "TEST.SZ",
        "warning_event_id": (
            f"{warning_id}|{lifecycle_event}|{decision_date}|v{version}"
        ),
        "warning_id": warning_id,
        "warning_type": "FORMING_DIVERGENCE_WARNING",
        "lifecycle_event": lifecycle_event,
        "warning_status": status or (
            lifecycle_event if lifecycle_event in terminal_statuses else "ACTIVE"
        ),
        "source_kind": (
            "FORMING_PEAK"
            if lifecycle_event in {"OPENED", "REFRESHED"}
            else "FORMAL_SIGNAL"
            if lifecycle_event == "ESCALATED"
            else "DAILY_RSI"
        ),
        "source_peak_id": f"FPK-{warning_id}",
        "source_version": version,
        "source_peak_date": decision_date,
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
        "local_rsi_delta": -2.0,
        "anchor_rsi_delta": -3.0,
        "warning_reason": f"FORMING_DIVERGENCE_{lifecycle_event}",
        "warning_evidence": "{}",
        "end_reason": end_reason,
        "linked_formal_signal_ref": linked_formal_signal_ref,
        "position_effect": "NONE",
        "recommended_position_cap": None,
        "is_warmup": decision_date < "2026-01-05",
        "is_display_range": "2026-01-05" <= decision_date <= "2026-02-10",
    })
    return row


def _warning_frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=WARNING_EVENT_COLUMNS)


def _result(
    events: pd.DataFrame,
    *,
    symbol: str = "TEST.SZ",
    dates: list[str] | None = None,
    closes: list[float] | None = None,
) -> AnalysisResult:
    dates = dates or [
        "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13",
        "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-19",
        "2026-01-20", "2026-01-21", "2026-01-22", "2026-01-23",
        "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29",
        "2026-01-30", "2026-02-02", "2026-02-03", "2026-02-04",
        "2026-02-05", "2026-02-06", "2026-02-09", "2026-02-10",
    ]
    closes = closes or [100.0 + index for index in range(len(dates))]
    daily = pd.DataFrame({
        "date": dates,
        "close": closes,
        "rsi": [60.0 + index / 10 for index in range(len(dates))],
    })
    copied_events = events.copy(deep=True)
    if not copied_events.empty:
        copied_events["symbol"] = symbol
    return AnalysisResult(
        symbol=symbol,
        name=f"Name {symbol}",
        daily_features=daily,
        peaks=pd.DataFrame(),
        canonical_peaks=pd.DataFrame(),
        signals=pd.DataFrame(columns=["signal_type", "is_display_range"]),
        state_log=pd.DataFrame(),
        cycle_log=pd.DataFrame(),
        rsi_audit=pd.DataFrame(),
        warnings=[],
        metadata={
            "display_start_date": "2026-01-05",
            "display_end_date": "2026-02-10",
            "calculation_start_date": "2026-01-02",
            "calculation_end_date": "2026-02-10",
            "input_checksum_sha256": f"CHECKSUM-{symbol}",
            "display_row_count": len(daily) - 1,
            "backtest_eligible": True,
            "warmup_satisfied": True,
            "indicator_ready_on_display_start": True,
        },
        warning_events=copied_events,
    )


def _manifest(*symbols: str) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": list(symbols),
        "sample_group": ["GROUP"] * len(symbols),
        "rationale": ["test"] * len(symbols),
    })


def test_cohort_and_carry_in_are_separated() -> None:
    result = _result(_warning_frame(
        _event("W-CARRY", "OPENED", "2026-01-02"),
        _event(
            "W-CARRY",
            "INVALIDATED",
            "2026-01-06",
            end_reason="FORMING_CONDITION_BROKEN",
        ),
        _event("W-COHORT", "OPENED", "2026-01-05"),
    ))

    validated = validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
    )

    assert validated.summary["carry_in_warning_count"] == 1
    assert validated.summary["cohort_warning_count"] == 1
    assert validated.outcomes["warning_id"].tolist() == ["W-COHORT"]


def test_cutoff_does_not_leak_future_terminal_event() -> None:
    result = _result(_warning_frame(
        _event("W-FUTURE", "OPENED", "2026-01-05"),
        _event(
            "W-FUTURE",
            "ESCALATED",
            "2026-02-11",
            linked_formal_signal_ref="FUTURE-FORMAL",
        ),
    ))

    validated = validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
    )
    row = validated.outcomes.iloc[0]

    assert row["as_of_status"] == "ACTIVE"
    assert pd.isna(row["terminal_date"])
    assert pd.isna(row["lead_to_escalation_trading_days"])
    assert row["latest_event"] == "OPENED"
    assert row["duration_trading_days"] == 26


def test_duration_uses_trading_row_difference_across_weekend() -> None:
    result = _result(
        _warning_frame(
            _event("W-WEEKEND", "OPENED", "2026-01-09"),
            _event(
                "W-WEEKEND",
                "INVALIDATED",
                "2026-01-12",
                end_reason="FORMING_CONDITION_BROKEN",
            ),
        ),
        dates=["2026-01-09", "2026-01-12"],
        closes=[100.0, 99.0],
    )
    result.metadata["display_start_date"] = "2026-01-09"
    result.metadata["display_end_date"] = "2026-01-12"

    validated = validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-09",
        display_end_date="2026-01-12",
    )

    assert validated.outcomes.iloc[0]["duration_trading_days"] == 1


def test_forward_horizon_formulas_are_exact() -> None:
    result = _result(
        _warning_frame(_event("W-PATH", "OPENED", "2026-01-05")),
        dates=[
            "2026-01-05", "2026-01-06", "2026-01-07",
            "2026-01-08", "2026-01-09", "2026-01-12",
        ],
        closes=[100.0, 110.0, 90.0, 120.0, 80.0, 105.0],
    )
    result.metadata["display_start_date"] = "2026-01-05"
    result.metadata["display_end_date"] = "2026-01-12"

    row = validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-05",
        display_end_date="2026-01-12",
    ).outcomes.iloc[0]

    assert row["forward_return_1"] == pytest.approx(0.10)
    assert row["max_forward_return_1"] == pytest.approx(0.10)
    assert row["min_forward_return_1"] == pytest.approx(0.10)
    assert row["forward_return_3"] == pytest.approx(0.20)
    assert row["max_forward_return_3"] == pytest.approx(0.20)
    assert row["min_forward_return_3"] == pytest.approx(-0.10)
    assert row["forward_return_5"] == pytest.approx(0.05)
    assert row["max_forward_return_5"] == pytest.approx(0.20)
    assert row["min_forward_return_5"] == pytest.approx(-0.20)


def test_incomplete_horizons_are_null_and_do_not_read_past_cutoff() -> None:
    result = _result(
        _warning_frame(_event("W-LATE", "OPENED", "2026-01-09")),
        dates=[
            "2026-01-05", "2026-01-06", "2026-01-07",
            "2026-01-08", "2026-01-09", "2026-01-12",
        ],
        closes=[95.0, 96.0, 97.0, 98.0, 100.0, 101.0],
    )
    result.metadata["display_end_date"] = "2026-01-09"

    row = validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-05",
        display_end_date="2026-01-09",
    ).outcomes.iloc[0]

    for horizon in HORIZONS:
        assert not bool(row[f"horizon_{horizon}_complete"])
        assert pd.isna(row[f"forward_return_{horizon}"])
        assert pd.isna(row[f"max_forward_return_{horizon}"])
        assert pd.isna(row[f"min_forward_return_{horizon}"])


def test_refresh_count_and_event_counts_remain_separate() -> None:
    result = _result(_warning_frame(
        _event("W-REFRESH", "OPENED", "2026-01-05"),
        _event("W-REFRESH", "REFRESHED", "2026-01-06", version=2),
        _event("W-REFRESH", "REFRESHED", "2026-01-07", version=3),
        _event(
            "W-REFRESH",
            "INVALIDATED",
            "2026-01-08",
            version=3,
            end_reason="FORMING_CONDITION_BROKEN",
        ),
    ))

    validated = validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
    )

    assert validated.summary["cohort_warning_count"] == 1
    assert validated.summary["refreshed_event_count"] == 2
    assert validated.outcomes.iloc[0]["refresh_count"] == 2


def test_contract_failure_is_retained_without_outcome_rows() -> None:
    result = _result(_warning_frame(
        _event("W-BROKEN", "OPENED", "2026-01-05"),
        _event(
            "W-BROKEN",
            "INVALIDATED",
            "2026-01-06",
            end_reason="FORMING_CONDITION_BROKEN",
        ),
        _event("W-BROKEN", "REFRESHED", "2026-01-07", version=2),
    ))

    bundle = build_validation_bundle(
        _manifest("TEST.SZ"),
        {"TEST.SZ": result},
        names_by_symbol={"TEST.SZ": "Test"},
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
        chart_path_root="outputs/validation/v04_phase4",
    )

    assert bundle.warning_outcomes.empty
    assert not bool(bundle.sample_summary.iloc[0]["contract_validation_passed"])
    assert "after terminal" in bundle.sample_summary.iloc[0]["error"]


def test_empty_warning_sample_succeeds_and_report_is_generated() -> None:
    bundle = build_validation_bundle(
        _manifest("TEST.SZ"),
        {"TEST.SZ": _result(_warning_frame())},
        names_by_symbol={"TEST.SZ": "Test"},
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
        chart_path_root="outputs/validation/v04_phase4",
    )

    assert bundle.warning_outcomes.empty
    assert bundle.sample_summary.iloc[0]["cohort_warning_count"] == 0
    assert bool(bundle.sample_summary.iloc[0]["contract_validation_passed"])
    assert "1 个样本中 1 个成功，0 个失败" in bundle.validation_report


def test_validation_does_not_mutate_analysis_result() -> None:
    result = _result(_warning_frame(
        _event("W-IMMUTABLE", "OPENED", "2026-01-05"),
    ))
    frame_names = (
        "daily_features", "peaks", "canonical_peaks", "signals", "state_log",
        "cycle_log", "rsi_audit", "warning_events",
    )
    before_frames = {
        name: getattr(result, name).copy(deep=True) for name in frame_names
    }
    before_warnings = deepcopy(result.warnings)
    before_metadata = deepcopy(result.metadata)

    validate_sample_result(
        result,
        sample_group="GROUP",
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
    )

    for name in frame_names:
        pd.testing.assert_frame_equal(getattr(result, name), before_frames[name])
    assert result.warnings == before_warnings
    assert result.metadata == before_metadata


def test_multisymbol_sorting_is_stable() -> None:
    manifest = _manifest("ZZZ.SZ", "AAA.SZ", "MMM.SZ")
    results = {
        symbol: _result(
            _warning_frame(_event(f"W-{symbol}", "OPENED", "2026-01-05")),
            symbol=symbol,
        )
        for symbol in manifest["symbol"]
    }

    bundle = build_validation_bundle(
        manifest,
        results,
        names_by_symbol={symbol: f"Name {symbol}" for symbol in results},
        display_start_date="2026-01-05",
        display_end_date="2026-02-10",
        chart_path_root="outputs/validation/v04_phase4",
    )

    assert bundle.sample_summary["symbol"].tolist() == [
        "ZZZ.SZ", "AAA.SZ", "MMM.SZ",
    ]
    assert bundle.warning_outcomes["symbol"].tolist() == [
        "AAA.SZ", "MMM.SZ", "ZZZ.SZ",
    ]


def test_private_frozen_sample_regression_and_isolation() -> None:
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
    frame_names = (
        "daily_features", "peaks", "canonical_peaks", "signals", "state_log",
        "cycle_log", "rsi_audit", "warning_events",
    )
    before = {name: getattr(result, name).copy(deep=True) for name in frame_names}
    warnings_before = deepcopy(result.warnings)
    metadata_before = deepcopy(result.metadata)

    validated = validate_sample_result(
        result,
        sample_group="AI_OPTICAL",
        display_start_date="2026-05-01",
        display_end_date="2026-07-20",
    )
    formal_types = {
        SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value,
        SignalType.NEAR_HIGH_BEARISH_DIVERGENCE.value,
    }

    assert int(result.signals["signal_type"].isin(formal_types).sum()) == 3
    assert result.warning_events["lifecycle_event"].value_counts().to_dict() == {
        "REFRESHED": 9,
        "OPENED": 7,
        "INVALIDATED": 4,
        "ESCALATED": 3,
    }
    assert validated.summary["active_warning_count"] == 0
    assert validated.summary["escalated_warning_count"] == 3
    assert validated.summary["cleared_warning_count"] == 0
    assert validated.summary["invalidated_warning_count"] == 1
    snapshot = _warning_reporting_snapshot(
        result.warning_events,
        display_start_date="2026-05-01",
        display_end_date="2026-07-20",
    )
    assert snapshot["state_counts"] == {
        "ACTIVE": 0,
        "ESCALATED": 3,
        "CLEARED": 0,
        "INVALIDATED": 4,
    }
    for name in frame_names:
        pd.testing.assert_frame_equal(getattr(result, name), before[name])
    assert result.warnings == warnings_before
    assert result.metadata == metadata_before


def test_script_persists_failures_before_sdk_logout_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAdapter:
        def __init__(self, **_: object) -> None:
            pass

        def get_code_info(self) -> pd.DataFrame:
            raise RuntimeError("synthetic setup failure")

        def close(self) -> None:
            raise SystemExit(0)

    monkeypatch.setattr(
        run_v04_phase4_validation, "AmazingDataAdapter", FakeAdapter
    )
    work_dir = Path(".runtime") / "script-failure-test"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = work_dir / "manifest.csv"
    output = work_dir / "output"
    _manifest("TEST.SZ").to_csv(manifest, index=False)

    exit_code = run_v04_phase4_validation._run_validation([
        "--manifest", str(manifest),
        "--display-start", "2026-01-05",
        "--display-end", "2026-02-10",
        "--adjust", "forward",
        "--output-dir", str(output),
    ])

    assert exit_code == 1
    summary = pd.read_csv(output / "sample_summary.csv")
    assert summary["symbol"].tolist() == ["TEST.SZ"]
    assert "synthetic setup failure" in summary.iloc[0]["error"]


def test_script_parent_returns_nonzero_from_fresh_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_dir = Path(".runtime") / "script-parent-test"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = work_dir / "manifest.csv"
    output = work_dir / "output"
    output.mkdir(parents=True, exist_ok=True)
    _manifest("TEST.SZ").to_csv(manifest, index=False)

    def fake_run(*_: object, **__: object) -> object:
        pd.DataFrame({
            "symbol": ["TEST.SZ"],
            "error": ["synthetic worker failure"],
        }).to_csv(output / "sample_summary.csv", index=False)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(run_v04_phase4_validation.subprocess, "run", fake_run)
    exit_code = run_v04_phase4_validation.main([
        "--manifest", str(manifest),
        "--display-start", "2026-01-05",
        "--display-end", "2026-02-10",
        "--adjust", "forward",
        "--output-dir", str(output),
    ])

    assert exit_code == 1
