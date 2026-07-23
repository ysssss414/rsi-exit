from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from rsi_exit.actionability import (
    ActionabilityValidationError,
    analyze_actionability_sample,
    build_actionability_summary,
    build_formal_warning_linkage,
)
from rsi_exit.config import load_config
from rsi_exit.models import SignalType
from rsi_exit.pipeline import analyze_bars
from rsi_exit.release_check import load_frozen_bars
from rsi_exit.warning_events import WARNING_EVENT_COLUMNS


PRIVATE_REGRESSION_BASELINE = (
    Path(__file__).parents[1]
    / "outputs"
    / "v0.2.1_baseline"
    / "300308.SZ_v0.2.1_frozen_baseline.zip"
)
PHASE4_DOCS = (
    Path(__file__).parents[1] / "docs" / "validation" / "v04_phase4"
)
FORMAL_TYPE = SignalType.NEW_HIGH_BEARISH_DIVERGENCE.value
ACTIONABILITY_SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "run_v04_phase41_actionability.py"
)
_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "run_v04_phase41_actionability",
    ACTIONABILITY_SCRIPT,
)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"cannot load actionability script: {ACTIONABILITY_SCRIPT}")
actionability_script = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(actionability_script)


def _daily(
    dates: list[str] | None = None,
    *,
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
) -> pd.DataFrame:
    dates = dates or [
        "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13",
        "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-19",
        "2026-01-20", "2026-01-21", "2026-01-22", "2026-01-23",
        "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29",
        "2026-01-30", "2026-02-02", "2026-02-03", "2026-02-04",
        "2026-02-05", "2026-02-06", "2026-02-09", "2026-02-10",
    ]
    size = len(dates)
    opens = opens or [100.0 + index for index in range(size)]
    highs = highs or [value + 2.0 for value in opens]
    lows = lows or [value - 2.0 for value in opens]
    closes = closes or [value + 1.0 for value in opens]
    return pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "rsi": [60.0 + index / 10 for index in range(size)],
    })


def _formal_ref(
    warning_id: str,
    decision_date: str,
    *,
    symbol: str = "TEST.SZ",
    canonical_id: str | None = None,
    canonical_version: int = 1,
    chain_id: str | None = None,
) -> str:
    canonical_id = canonical_id or f"CAN-{warning_id}"
    chain_id = chain_id or f"CHAIN-{warning_id}"
    return (
        f"{symbol}|{FORMAL_TYPE}|{canonical_id}@v{canonical_version}|"
        f"{decision_date}|{chain_id}"
    )


def _event(
    warning_id: str,
    lifecycle_event: str,
    decision_date: str,
    *,
    version: int = 1,
    symbol: str = "TEST.SZ",
    linked_formal_signal_ref: str | None = None,
    canonical_id: str | None = None,
    canonical_version: int | None = None,
    chain_id: str | None = None,
) -> dict[str, object]:
    terminal = lifecycle_event in {"ESCALATED", "CLEARED", "INVALIDATED"}
    canonical_id = canonical_id or (
        f"CAN-{warning_id}" if lifecycle_event == "ESCALATED" else None
    )
    canonical_version = canonical_version or (
        1 if lifecycle_event == "ESCALATED" else None
    )
    chain_id = chain_id or f"CHAIN-{warning_id}"
    row = {column: None for column in WARNING_EVENT_COLUMNS}
    row.update({
        "symbol": symbol,
        "warning_event_id": (
            f"{warning_id}|{lifecycle_event}|{decision_date}|v{version}"
        ),
        "warning_id": warning_id,
        "warning_type": "FORMING_DIVERGENCE_WARNING",
        "lifecycle_event": lifecycle_event,
        "warning_status": lifecycle_event if terminal else "ACTIVE",
        "source_kind": (
            "FORMING_PEAK"
            if lifecycle_event in {"OPENED", "REFRESHED"}
            else "FORMAL_SIGNAL"
            if lifecycle_event in {"ESCALATED", "CLEARED"}
            else "DAILY_RSI"
        ),
        "source_peak_id": f"FPK-{warning_id}",
        "source_version": version,
        "source_canonical_peak_id": canonical_id,
        "source_canonical_version": canonical_version,
        "source_peak_date": decision_date,
        "observation_date": decision_date,
        "decision_date": decision_date,
        "available_date": decision_date,
        "momentum_anchor_id": "PK-ANCHOR",
        "momentum_anchor_version": 1,
        "last_structural_peak_id": "PK-LAST",
        "last_structural_peak_version": 1,
        "latest_confirmed_canonical_id": canonical_id,
        "latest_confirmed_canonical_version": canonical_version,
        "divergence_chain_id": chain_id,
        "risk_cycle_id": "CYCLE-1",
        "price_relation": "STRICT_NEW_HIGH",
        "local_rsi_delta": -2.0,
        "anchor_rsi_delta": -3.0,
        "warning_reason": f"FORMING_DIVERGENCE_{lifecycle_event}",
        "warning_evidence": "{}",
        "end_reason": (
            "FORMAL_DIVERGENCE_CONFIRMED"
            if lifecycle_event == "ESCALATED"
            else "MOMENTUM_ANCHOR_REBUILT"
            if lifecycle_event == "CLEARED"
            else "FORMING_CONDITION_BROKEN"
            if lifecycle_event == "INVALIDATED"
            else None
        ),
        "linked_formal_signal_ref": linked_formal_signal_ref,
        "position_effect": "NONE",
        "recommended_position_cap": None,
        "is_warmup": False,
        "is_display_range": True,
    })
    return row


def _events(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=WARNING_EVENT_COLUMNS)


def _formal_signal(
    warning_id: str,
    decision_date: str,
    *,
    canonical_id: str | None = None,
    canonical_version: int = 1,
    chain_id: str | None = None,
) -> dict[str, object]:
    return {
        "decision_date": decision_date,
        "signal_type": FORMAL_TYPE,
        "signal_status": "FORMAL",
        "current_canonical_peak_id": canonical_id or f"CAN-{warning_id}",
        "current_canonical_version": canonical_version,
        "divergence_chain_id": chain_id or f"CHAIN-{warning_id}",
        "is_display_range": True,
    }


def _analyze(
    events: pd.DataFrame,
    *,
    daily: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
    expected_checksum: str = "CHECKSUM",
    audit_checksum: str = "CHECKSUM",
    display_start_date: str = "2026-01-02",
    display_end_date: str = "2026-02-10",
):
    daily = daily if daily is not None else _daily()
    signals = signals if signals is not None else pd.DataFrame(
        columns=[
            "decision_date", "signal_type", "signal_status",
            "current_canonical_peak_id", "current_canonical_version",
            "divergence_chain_id", "is_display_range",
        ]
    )
    dates = pd.to_datetime(daily["date"])
    display_count = int(
        dates.between(
            pd.Timestamp(display_start_date), pd.Timestamp(display_end_date)
        ).sum()
    )
    return analyze_actionability_sample(
        symbol="TEST.SZ",
        name="Test Name",
        sample_group="GROUP",
        expected_checksum=expected_checksum,
        expected_display_bar_count=display_count,
        display_start_date=display_start_date,
        display_end_date=display_end_date,
        daily_features=daily,
        warning_events=events,
        signals=signals,
        rsi_audit=pd.DataFrame({
            "input_checksum_sha256": [audit_checksum, audit_checksum]
        }),
    )


def test_action_date_is_next_actual_trading_row_after_event() -> None:
    daily = _daily([
        "2026-01-02",
        "2026-01-06",
        "2026-01-07",
    ])
    result = _analyze(
        _events(_event("W1", "OPENED", "2026-01-02")),
        daily=daily,
        display_end_date="2026-01-07",
    )

    row = result.event_outcomes.iloc[0]
    assert row["event_decision_date"] == "2026-01-02"
    assert row["action_date"] == "2026-01-06"
    assert bool(row["action_available"]) is True
    assert row["event_close"] == pytest.approx(daily.iloc[0]["close"])
    assert row["event_rsi"] == pytest.approx(daily.iloc[0]["rsi"])


def test_action_returns_start_at_open_and_use_high_and_low() -> None:
    daily = _daily(
        ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
        opens=[80.0, 100.0, 101.0, 102.0],
        highs=[82.0, 110.0, 120.0, 115.0],
        lows=[78.0, 90.0, 80.0, 95.0],
        closes=[81.0, 105.0, 95.0, 110.0],
    )
    result = _analyze(
        _events(_event("W1", "OPENED", "2026-01-02")),
        daily=daily,
        display_end_date="2026-01-07",
    )

    row = result.event_outcomes.iloc[0]
    assert row["action_open"] == 100.0
    assert row["action_forward_close_return_1"] == pytest.approx(0.05)
    assert row["action_max_high_return_1"] == pytest.approx(0.10)
    assert row["action_min_low_return_1"] == pytest.approx(-0.10)
    assert row["action_forward_close_return_3"] == pytest.approx(0.10)
    assert row["action_max_high_return_3"] == pytest.approx(0.20)
    assert row["action_min_low_return_3"] == pytest.approx(-0.20)


def test_action_horizons_do_not_read_past_display_end() -> None:
    daily = _daily(
        ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
        opens=[90.0, 95.0, 100.0, 1000.0],
        highs=[91.0, 96.0, 101.0, 2000.0],
        lows=[89.0, 94.0, 99.0, 1.0],
        closes=[90.0, 95.0, 101.0, 1500.0],
    )
    result = _analyze(
        _events(_event("W1", "OPENED", "2026-01-05")),
        daily=daily,
        display_end_date="2026-01-06",
    )

    row = result.event_outcomes.iloc[0]
    assert row["action_date"] == "2026-01-06"
    assert bool(row["action_horizon_1_complete"]) is True
    assert row["action_forward_close_return_1"] == pytest.approx(0.01)
    assert bool(row["action_horizon_3_complete"]) is False
    assert pd.isna(row["action_forward_close_return_3"])
    assert pd.isna(row["action_max_high_return_3"])
    assert pd.isna(row["action_min_low_return_3"])


def test_opened_summary_does_not_group_by_future_terminal_status() -> None:
    ref = _formal_ref("W1", "2026-01-06")
    events = _events(
        _event("W1", "OPENED", "2026-01-02"),
        _event(
            "W1",
            "ESCALATED",
            "2026-01-06",
            linked_formal_signal_ref=ref,
        ),
        _event("W2", "OPENED", "2026-01-05"),
        _event("W2", "INVALIDATED", "2026-01-07"),
    )
    result = _analyze(
        events,
        signals=pd.DataFrame([_formal_signal("W1", "2026-01-06")]),
    )
    summary = build_actionability_summary(
        result.event_outcomes,
        sample_groups=["GROUP"],
    )
    opened = summary.loc[
        (summary["lifecycle_event"] == "OPENED")
        & (summary["sample_group"] == "ALL")
        & (summary["horizon_days"] == 1)
    ]

    assert len(opened) == 1
    assert opened.iloc[0]["event_count"] == 2
    assert "ex_post_terminal_status" not in summary.columns


def test_formal_warning_linkage_matches_unique_event() -> None:
    ref = _formal_ref("W1", "2026-01-06")
    linkage = build_formal_warning_linkage(
        symbol="TEST.SZ",
        signals=pd.DataFrame([_formal_signal("W1", "2026-01-06")]),
        warning_events=_events(_event(
            "W1",
            "ESCALATED",
            "2026-01-06",
            linked_formal_signal_ref=ref,
        )),
        display_start_date="2026-01-02",
        display_end_date="2026-02-10",
    )

    assert linkage["linkage_status"].tolist() == ["MATCHED"]
    assert linkage["error"].tolist() == [""]


def test_missing_formal_linkage_is_explicit_failure() -> None:
    linkage = build_formal_warning_linkage(
        symbol="TEST.SZ",
        signals=pd.DataFrame([_formal_signal("W1", "2026-01-06")]),
        warning_events=_events(),
        display_start_date="2026-01-02",
        display_end_date="2026-02-10",
    )

    assert linkage["linkage_status"].tolist() == ["MISSING_ESCALATED"]
    assert "no ESCALATED" in linkage.iloc[0]["error"]


def test_one_formal_to_multiple_escalated_is_explicit_failure() -> None:
    ref = _formal_ref("W1", "2026-01-06")
    linkage = build_formal_warning_linkage(
        symbol="TEST.SZ",
        signals=pd.DataFrame([_formal_signal("W1", "2026-01-06")]),
        warning_events=_events(
            _event(
                "W1",
                "ESCALATED",
                "2026-01-06",
                linked_formal_signal_ref=ref,
            ),
            _event(
                "W2",
                "ESCALATED",
                "2026-01-06",
                linked_formal_signal_ref=ref,
                canonical_id="CAN-W1",
                chain_id="CHAIN-W1",
            ),
        ),
        display_start_date="2026-01-02",
        display_end_date="2026-02-10",
    )

    assert set(linkage["linkage_status"]) == {"ONE_TO_MANY"}
    assert linkage["error"].str.contains("multiple ESCALATED").all()


def test_multiple_formals_to_one_escalated_is_explicit_failure() -> None:
    formal = _formal_signal("W1", "2026-01-06")
    ref = _formal_ref("W1", "2026-01-06")
    linkage = build_formal_warning_linkage(
        symbol="TEST.SZ",
        signals=pd.DataFrame([formal, formal.copy()]),
        warning_events=_events(_event(
            "W1",
            "ESCALATED",
            "2026-01-06",
            linked_formal_signal_ref=ref,
        )),
        display_start_date="2026-01-02",
        display_end_date="2026-02-10",
    )

    assert set(linkage["linkage_status"]) == {"MANY_TO_ONE"}
    assert linkage["error"].str.contains("multiple formal").all()


def test_opened_to_escalated_wait_cost_uses_exact_prices_and_rows() -> None:
    ref = _formal_ref("W1", "2026-01-06")
    daily = _daily(
        ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
        opens=[99.0, 96.0, 91.0, 85.0],
        highs=[101.0, 98.0, 93.0, 87.0],
        lows=[98.0, 94.0, 89.0, 83.0],
        closes=[100.0, 95.0, 90.0, 86.0],
    )
    result = _analyze(
        _events(
            _event("W1", "OPENED", "2026-01-02"),
            _event("W1", "REFRESHED", "2026-01-05", version=2),
            _event(
                "W1",
                "ESCALATED",
                "2026-01-06",
                version=2,
                linked_formal_signal_ref=ref,
            ),
        ),
        daily=daily,
        signals=pd.DataFrame([_formal_signal("W1", "2026-01-06")]),
        display_end_date="2026-01-07",
    )

    row = result.opened_to_escalated.iloc[0]
    assert row["lead_trading_days"] == 2
    assert row["opened_close"] == 100.0
    assert row["escalated_close"] == 90.0
    assert row["escalated_action_date"] == "2026-01-07"
    assert row["escalated_action_open"] == 85.0
    assert row["opened_to_escalated_close_return"] == pytest.approx(-0.10)
    assert row["opened_close_to_escalated_action_open_return"] == pytest.approx(
        -0.15
    )
    assert row["refresh_count"] == 1


def test_last_event_has_no_action_date_or_action_metrics() -> None:
    daily = _daily(["2026-01-02", "2026-01-05"])
    result = _analyze(
        _events(_event("W1", "OPENED", "2026-01-05")),
        daily=daily,
        display_end_date="2026-01-05",
    )

    row = result.event_outcomes.iloc[0]
    assert pd.isna(row["action_date"])
    assert pd.isna(row["action_open"])
    assert pd.isna(row["action_close"])
    assert bool(row["action_available"]) is False
    for horizon in (1, 3, 5, 10, 20):
        assert bool(row[f"action_horizon_{horizon}_complete"]) is False
        assert pd.isna(row[f"action_forward_close_return_{horizon}"])
        assert pd.isna(row[f"action_max_high_return_{horizon}"])
        assert pd.isna(row[f"action_min_low_return_{horizon}"])


def test_actionability_inputs_are_immutable() -> None:
    daily = _daily()
    events = _events(_event("W1", "OPENED", "2026-01-02"))
    signals = pd.DataFrame(columns=[
        "decision_date", "signal_type", "signal_status",
        "current_canonical_peak_id", "current_canonical_version",
        "divergence_chain_id", "is_display_range",
    ])
    audit = pd.DataFrame({"input_checksum_sha256": ["CHECKSUM"]})
    before = {
        "daily": daily.copy(deep=True),
        "events": events.copy(deep=True),
        "signals": signals.copy(deep=True),
        "audit": audit.copy(deep=True),
    }

    analyze_actionability_sample(
        symbol="TEST.SZ",
        name="Test Name",
        sample_group="GROUP",
        expected_checksum="CHECKSUM",
        expected_display_bar_count=len(daily),
        display_start_date="2026-01-02",
        display_end_date="2026-02-10",
        daily_features=daily,
        warning_events=events,
        signals=signals,
        rsi_audit=audit,
    )

    pd.testing.assert_frame_equal(daily, before["daily"])
    pd.testing.assert_frame_equal(events, before["events"])
    pd.testing.assert_frame_equal(signals, before["signals"])
    pd.testing.assert_frame_equal(audit, before["audit"])


def test_checksum_mismatch_fails_the_sample() -> None:
    with pytest.raises(ActionabilityValidationError, match="checksum mismatch"):
        _analyze(
            _events(_event("W1", "OPENED", "2026-01-02")),
            expected_checksum="EXPECTED",
            audit_checksum="ACTUAL",
        )


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

    actionability = analyze_actionability_sample(
        symbol=result.symbol,
        name=result.name,
        sample_group="AI_OPTICAL",
        expected_checksum=result.metadata["input_checksum_sha256"],
        expected_display_bar_count=len(result.daily_features),
        display_start_date="2026-05-01",
        display_end_date="2026-07-20",
        daily_features=result.daily_features,
        warning_events=result.warning_events,
        signals=result.signals,
        rsi_audit=result.rsi_audit,
    )

    formal_types = {
        SignalType.BEARISH_DIVERGENCE.value,
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
    assert actionability.event_outcomes["lifecycle_event"].value_counts().to_dict() == {
        "OPENED": 4,
        "INVALIDATED": 1,
        "ESCALATED": 3,
    }
    assert actionability.formal_warning_linkage["linkage_status"].eq(
        "MATCHED"
    ).all()
    for name in frame_names:
        pd.testing.assert_frame_equal(getattr(result, name), before[name])
    assert result.warnings == warnings_before
    assert result.metadata == metadata_before


def test_phase4_committed_validation_artifacts_remain_byte_identical() -> None:
    paths = [
        PHASE4_DOCS / "sample_summary.csv",
        PHASE4_DOCS / "warning_outcomes.csv",
        PHASE4_DOCS / "outcome_summary.csv",
        PHASE4_DOCS / "validation_report.md",
    ]
    before = {path: path.read_bytes() for path in paths}

    _analyze(_events(_event("W1", "OPENED", "2026-01-02")))

    assert {path: path.read_bytes() for path in paths} == before


def test_actionability_script_returns_nonzero_for_missing_phase4_output(
    tmp_path: Path,
) -> None:
    assert actionability_script.main([
        "--phase4-output",
        str(tmp_path / "missing"),
        "--output-dir",
        str(tmp_path / "output"),
    ]) == 1


def test_actionability_script_returns_nonzero_for_any_failed_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedBundle:
        failed_count = 1

    monkeypatch.setattr(
        actionability_script,
        "load_phase4_actionability",
        lambda _: FailedBundle(),
    )
    monkeypatch.setattr(
        actionability_script,
        "write_actionability_bundle",
        lambda *_: {},
    )

    assert actionability_script.main([
        "--phase4-output",
        str(tmp_path / "phase4"),
        "--output-dir",
        str(tmp_path / "output"),
    ]) == 1
