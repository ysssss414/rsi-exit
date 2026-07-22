from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import zipfile

import numpy as np
import pandas as pd
import pytest

from rsi_exit.config import load_config
from rsi_exit.freeze_baseline import TABLE_MEMBERS, validate_frozen_archive
from rsi_exit.models import (
    SignalType,
    WarningLifecycleEvent,
    WarningPositionEffect,
    WarningSourceKind,
    WarningStatus,
    WarningType,
)
from rsi_exit.pipeline import analyze_bars
from rsi_exit.reporting import build_summary, write_outputs
from rsi_exit.warning_events import (
    WARNING_EVENT_COLUMNS,
    WarningSourceContractError,
    build_warning_events,
    warning_events_frame,
)


FROZEN_BASELINE_SHA256 = (
    "932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52"
)
FROZEN_BASELINE = (
    Path(__file__).parents[1]
    / "baselines"
    / "300308.SZ_v0.3.0_frozen_baseline.zip"
)


def warning_source(
    *,
    version: int = 1,
    decision_date: str = "2026-01-05",
    **overrides: object,
) -> dict[str, object]:
    source: dict[str, object] = {
        "signal_type": SignalType.DIVERGENCE_FORMING.value,
        "signal_status": "FORMING",
        "price_relation": "STRICT_NEW_HIGH",
        "candidate_peak_id": "FPK0001",
        "canonical_version": version,
        "current_peak_date": decision_date,
        "decision_date": decision_date,
        "momentum_anchor_canonical_id": "P0001",
        "momentum_anchor_canonical_version": 2,
        "previous_canonical_peak_id": "P0002",
        "previous_canonical_version": 3,
        "divergence_chain_id": "DCHAIN0004",
        "risk_cycle_id": "CYCLE0005",
        "local_rsi_delta": -1.0,
        "anchor_rsi_delta": -2.5,
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


def _event_frame(*sources: dict[str, object], symbol: str = "TEST.SZ") -> pd.DataFrame:
    return warning_events_frame(build_warning_events(symbol=symbol, sources=sources))


def _canonical_id(prefix: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}{sha256(encoded).hexdigest().upper()}"


def test_warning_model_is_frozen_and_enums_are_approved() -> None:
    event = build_warning_events(symbol="TEST.SZ", sources=[warning_source()])[0]
    with pytest.raises(FrozenInstanceError):
        event.warning_id = "changed"  # type: ignore[misc]

    assert [item.value for item in WarningType] == ["FORMING_DIVERGENCE_WARNING"]
    assert [item.value for item in WarningLifecycleEvent] == [
        "OPENED", "REFRESHED", "ESCALATED", "CLEARED", "INVALIDATED",
    ]
    assert [item.value for item in WarningStatus] == [
        "ACTIVE", "ESCALATED", "CLEARED", "INVALIDATED",
    ]
    assert [item.value for item in WarningSourceKind] == ["FORMING_PEAK"]
    assert [item.value for item in WarningPositionEffect] == ["NONE"]


def test_warning_event_columns_and_empty_frame_are_fixed() -> None:
    assert WARNING_EVENT_COLUMNS == [
        "symbol", "warning_event_id", "warning_id", "warning_type",
        "lifecycle_event", "warning_status", "source_kind", "source_peak_id",
        "source_version", "source_canonical_peak_id", "source_canonical_version",
        "source_peak_date", "observation_date", "decision_date", "available_date",
        "momentum_anchor_id", "momentum_anchor_version", "last_structural_peak_id",
        "last_structural_peak_version", "latest_confirmed_canonical_id",
        "latest_confirmed_canonical_version", "divergence_chain_id", "risk_cycle_id",
        "price_relation", "local_rsi_delta", "anchor_rsi_delta", "warning_reason",
        "warning_evidence", "end_reason", "linked_formal_signal_ref",
        "position_effect", "recommended_position_cap", "is_warmup",
        "is_display_range",
    ]
    empty = warning_events_frame([])
    assert empty.empty
    assert empty.columns.tolist() == WARNING_EVENT_COLUMNS


@pytest.mark.parametrize("price_relation", [
    "STRICT_NEW_HIGH",
    "FORMAL_NEAR_HIGH_RETEST",
])
def test_approved_trigger_relations_open_warning(price_relation: str) -> None:
    frame = _event_frame(warning_source(price_relation=price_relation))
    assert len(frame) == 1
    assert frame.iloc[0]["lifecycle_event"] == "OPENED"


@pytest.mark.parametrize(("signal_type", "signal_status", "price_relation"), [
    ("INTRADAY_POTENTIAL_RETEST", "FORMING", "STRICT_NEW_HIGH"),
    ("NON_COMPARABLE_PEAK", "FORMING", "STRICT_NEW_HIGH"),
    ("STRUCTURAL_PEAK_WITHOUT_DIVERGENCE", "FORMING", "STRICT_NEW_HIGH"),
    ("DIVERGENCE_FORMING", "FORMAL", "STRICT_NEW_HIGH"),
    ("NEW_HIGH_BEARISH_DIVERGENCE", "FORMAL", "STRICT_NEW_HIGH"),
    ("DIVERGENCE_FORMING", "FORMING", "LOWER_HIGH"),
])
def test_non_trigger_sources_are_ignored_without_contract_validation(
    signal_type: str,
    signal_status: str,
    price_relation: str,
) -> None:
    source = warning_source(
        signal_type=signal_type,
        signal_status=signal_status,
        price_relation=price_relation,
        local_rsi_delta=float("nan"),
        structural_eligible=True,
    )
    assert build_warning_events(symbol="TEST.SZ", sources=[source]) == []


_MISSING = object()


@pytest.mark.parametrize(("field", "bad_value", "assertion"), [
    ("local_rsi_delta", -0.999, "local_rsi_delta <= -1.0"),
    ("anchor_rsi_delta", -0.999, "anchor_rsi_delta <= -1.0"),
    ("structural_eligible", True, "structural_eligible is False"),
    ("position_eligible", True, "position_eligible is False"),
    ("pending_action_type", "APPLY_SIGNAL_CAP", "pending_action_type is None"),
    ("momentum_anchor_canonical_id", _MISSING, "momentum_anchor_id"),
    ("previous_canonical_peak_id", _MISSING, "last_structural_peak_id"),
    ("divergence_chain_id", _MISSING, "divergence_chain_id"),
    ("risk_cycle_id", "", "risk_cycle_id"),
    ("current_peak_date", _MISSING, "source_peak_date"),
    ("decision_date", None, "decision_date"),
    ("local_rsi_delta", float("nan"), "local_rsi_delta is finite"),
    ("anchor_rsi_delta", float("nan"), "anchor_rsi_delta is finite"),
])
def test_trigger_source_contract_rejects_broken_facts(
    field: str,
    bad_value: object,
    assertion: str,
) -> None:
    source = warning_source()
    if bad_value is _MISSING:
        del source[field]
    else:
        source[field] = bad_value

    with pytest.raises(WarningSourceContractError) as exc_info:
        build_warning_events(symbol="TEST.SZ", sources=[source])
    message = str(exc_info.value)
    assert "symbol=TEST.SZ" in message
    assert "source_peak_id=FPK0001" in message
    assert "source_version=1" in message
    assert assertion in message


def test_contract_delta_boundary_minus_one_is_valid() -> None:
    event = build_warning_events(
        symbol="TEST.SZ",
        sources=[warning_source(local_rsi_delta=-1.0, anchor_rsi_delta=-1.0)],
    )[0]
    assert event.local_rsi_delta == -1.0
    assert event.anchor_rsi_delta == -1.0


def test_ids_match_canonical_sha256_payloads_and_are_symbol_scoped() -> None:
    source = warning_source()
    first = build_warning_events(symbol="TEST.SZ", sources=[source])[0]
    replay = build_warning_events(symbol="TEST.SZ", sources=[source])[0]
    other_symbol = build_warning_events(symbol="OTHER.SZ", sources=[source])[0]
    warning_payload = {
        "symbol": "TEST.SZ",
        "warning_type": "FORMING_DIVERGENCE_WARNING",
        "source_forming_peak_id": "FPK0001",
        "divergence_chain_id": "DCHAIN0004",
        "momentum_anchor_id": "P0001",
        "momentum_anchor_version": 2,
        "last_structural_peak_id": "P0002",
        "last_structural_peak_version": 3,
    }
    expected_warning_id = _canonical_id("FWARN-", warning_payload)
    expected_event_id = _canonical_id("WEVT-", {
        "warning_id": expected_warning_id,
        "lifecycle_event": "OPENED",
        "source_version": 1,
        "decision_date": "2026-01-05",
    })
    assert first.warning_id == replay.warning_id == expected_warning_id
    assert first.warning_event_id == replay.warning_event_id == expected_event_id
    assert other_symbol.warning_id != first.warning_id
    assert re.fullmatch(r"FWARN-[0-9A-F]{64}", first.warning_id)
    assert re.fullmatch(r"WEVT-[0-9A-F]{64}", first.warning_event_id)


@pytest.mark.parametrize(("change", "value"), [
    ("momentum_anchor_canonical_version", 9),
    ("previous_canonical_version", 9),
    ("divergence_chain_id", "DCHAIN9999"),
])
def test_warning_identity_changes_with_frozen_context(
    change: str,
    value: object,
) -> None:
    original = build_warning_events(
        symbol="TEST.SZ", sources=[warning_source()]
    )[0]
    changed = build_warning_events(
        symbol="TEST.SZ", sources=[warning_source(**{change: value})]
    )[0]
    assert changed.warning_id != original.warning_id


def test_opened_refreshed_dedupe_and_version_gaps() -> None:
    v1 = warning_source(version=1, decision_date="2026-01-05")
    v2 = warning_source(version=2, decision_date="2026-01-06")
    v3 = warning_source(version=3, decision_date="2026-01-07")
    frame = _event_frame(v1, v1.copy(), v2, v3)
    assert frame["warning_id"].nunique() == 1
    assert frame["source_version"].tolist() == [1, 2, 3]
    assert frame["lifecycle_event"].tolist() == ["OPENED", "REFRESHED", "REFRESHED"]
    assert frame["warning_reason"].tolist() == [
        "FORMING_DIVERGENCE_OPENED",
        "FORMING_DIVERGENCE_REFRESHED",
        "FORMING_DIVERGENCE_REFRESHED",
    ]
    assert frame["warning_event_id"].nunique() == 3

    gap = _event_frame(v1, warning_source(version=4, decision_date="2026-01-08"))
    assert gap["source_version"].tolist() == [1, 4]


def test_same_event_identity_with_different_evidence_is_rejected() -> None:
    first = warning_source()
    conflicting = warning_source(local_rsi_delta=-1.5)
    with pytest.raises(WarningSourceContractError, match="conflicting evidence"):
        build_warning_events(symbol="TEST.SZ", sources=[first, conflicting])


def test_same_version_on_different_dates_is_rejected() -> None:
    sources = [
        warning_source(version=1, decision_date="2026-01-05"),
        warning_source(version=1, decision_date="2026-01-06"),
    ]
    with pytest.raises(WarningSourceContractError, match="same version on different dates"):
        build_warning_events(symbol="TEST.SZ", sources=sources)


def test_version_regression_by_decision_date_is_rejected() -> None:
    sources = [
        warning_source(version=2, decision_date="2026-01-05"),
        warning_source(version=1, decision_date="2026-01-06"),
    ]
    with pytest.raises(WarningSourceContractError, match="version regression"):
        build_warning_events(symbol="TEST.SZ", sources=reversed(sources))


def test_new_frozen_context_opens_a_distinct_warning() -> None:
    first = warning_source(version=1, decision_date="2026-01-05")
    second = warning_source(
        version=2,
        decision_date="2026-01-06",
        momentum_anchor_canonical_version=3,
    )
    frame = _event_frame(first, second)
    assert frame["warning_id"].nunique() == 2
    assert frame["lifecycle_event"].tolist() == ["OPENED", "OPENED"]


def test_event_dates_nulls_position_and_evidence_are_phase1_only() -> None:
    frame = _event_frame(warning_source())
    row = frame.iloc[0]
    assert row["observation_date"] == row["decision_date"] == row["available_date"]
    assert row["warning_type"] == "FORMING_DIVERGENCE_WARNING"
    assert row["warning_status"] == "ACTIVE"
    assert row["source_kind"] == "FORMING_PEAK"
    assert row["position_effect"] == "NONE"
    for column in (
        "source_canonical_peak_id", "source_canonical_version", "end_reason",
        "linked_formal_signal_ref", "recommended_position_cap",
    ):
        assert pd.isna(row[column])
    assert "earliest_action_date" not in frame
    assert "effective_date" not in frame
    assert json.loads(row["warning_evidence"]) == {
        "anchor_rsi_delta": -2.5,
        "local_rsi_delta": -1.0,
        "price_relation": "STRICT_NEW_HIGH",
        "source_peak_date": "2026-01-05",
        "source_peak_id": "FPK0001",
        "source_signal_status": "FORMING",
        "source_signal_type": "DIVERGENCE_FORMING",
        "source_version": 1,
    }


def test_builder_is_non_mutating_prefix_consistent_and_input_order_independent() -> None:
    sources = [
        warning_source(version=1, decision_date="2026-01-05"),
        warning_source(version=2, decision_date="2026-01-06"),
        warning_source(version=3, decision_date="2026-01-07"),
    ]
    before = deepcopy(sources)
    full = _event_frame(*reversed(sources))
    prefix = _event_frame(*sources[:2])
    pd.testing.assert_frame_equal(
        prefix,
        full.loc[full["decision_date"] <= "2026-01-06"].reset_index(drop=True),
    )
    assert sources == before


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
    source.loc[24, "hard_exit"] = 1
    source.loc[25, ["close", "high", "open", "low"]] = [95, 95, 94.8, 94.5]
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


def test_pipeline_warning_layer_is_fully_isolated(monkeypatch) -> None:
    bars, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    normal = analyze_bars(bars, symbol="WARNING.ISOLATION", config=load_config())
    assert not normal.warning_events.empty

    monkeypatch.setattr("rsi_exit.pipeline.build_warning_events", lambda **_: [])
    isolated = analyze_bars(bars, symbol="WARNING.ISOLATION", config=load_config())
    assert isolated.warning_events.empty
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


def test_reporting_writes_separate_warning_csv_without_changing_summary(
    monkeypatch,
    tmp_path,
) -> None:
    bars, rsi = scripted_bars()
    install_scripted_rsi(monkeypatch, rsi)
    config = load_config()
    result = analyze_bars(bars, symbol="WARNING.REPORT", config=config)
    with_events_summary = build_summary(result, config)
    output = write_outputs(
        result,
        config=config,
        output_root=tmp_path / "with-events",
        plot=False,
    )
    written = pd.read_csv(output / "warning_events.csv", encoding="utf-8-sig")
    assert written.columns.tolist() == WARNING_EVENT_COLUMNS
    assert len(written) == len(result.warning_events)
    expected_signals = result.signals.copy()
    numeric_columns = expected_signals.select_dtypes(include=["number"]).columns
    expected_signals[numeric_columns] = expected_signals[numeric_columns].round(6)
    expected_signals = pd.read_csv(StringIO(expected_signals.to_csv(index=False)))
    pd.testing.assert_frame_equal(
        pd.read_csv(output / "signals.csv", encoding="utf-8-sig"),
        expected_signals,
        check_dtype=False,
    )

    empty_result = replace(result, warning_events=pd.DataFrame())
    empty_output = write_outputs(
        empty_result,
        config=config,
        output_root=tmp_path / "empty",
        plot=False,
    )
    empty_written = pd.read_csv(
        empty_output / "warning_events.csv", encoding="utf-8-sig"
    )
    assert empty_written.empty
    assert empty_written.columns.tolist() == WARNING_EVENT_COLUMNS
    assert build_summary(empty_result, config) == with_events_summary
    assert "## 警告" in with_events_summary
    assert result.warning_events.iloc[0]["warning_id"] not in with_events_summary


def test_v03_frozen_archive_and_release_contract_exclude_warning_events() -> None:
    assert all(attribute != "warning_events" for _, attribute in TABLE_MEMBERS)
    archive_bytes = FROZEN_BASELINE.read_bytes()
    assert sha256(archive_bytes).hexdigest().upper() == FROZEN_BASELINE_SHA256
    manifest = validate_frozen_archive(archive_bytes)
    assert manifest["formal_divergence_count"] == 3
    with zipfile.ZipFile(FROZEN_BASELINE) as archive:
        assert not any("warning_events" in member for member in archive.namelist())
