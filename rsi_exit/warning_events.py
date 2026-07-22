from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable, Mapping

import pandas as pd

from rsi_exit.models import (
    WarningEvent,
    WarningLifecycleEvent,
    WarningPositionEffect,
    WarningSourceKind,
    WarningStatus,
    WarningType,
)


WARNING_EVENT_COLUMNS = [
    "symbol",
    "warning_event_id",
    "warning_id",
    "warning_type",
    "lifecycle_event",
    "warning_status",
    "source_kind",
    "source_peak_id",
    "source_version",
    "source_canonical_peak_id",
    "source_canonical_version",
    "source_peak_date",
    "observation_date",
    "decision_date",
    "available_date",
    "momentum_anchor_id",
    "momentum_anchor_version",
    "last_structural_peak_id",
    "last_structural_peak_version",
    "latest_confirmed_canonical_id",
    "latest_confirmed_canonical_version",
    "divergence_chain_id",
    "risk_cycle_id",
    "price_relation",
    "local_rsi_delta",
    "anchor_rsi_delta",
    "warning_reason",
    "warning_evidence",
    "end_reason",
    "linked_formal_signal_ref",
    "position_effect",
    "recommended_position_cap",
    "is_warmup",
    "is_display_range",
]


TRIGGER_PRICE_RELATIONS = {
    "STRICT_NEW_HIGH",
    "FORMAL_NEAR_HIGH_RETEST",
}


class WarningSourceContractError(ValueError):
    """A triggering forming fact violates the approved source contract."""


@dataclass(frozen=True)
class _WarningSource:
    symbol: str
    warning_id: str
    source_peak_id: str
    source_version: int
    source_peak_date: str
    decision_date: str
    momentum_anchor_id: str
    momentum_anchor_version: int
    last_structural_peak_id: str
    last_structural_peak_version: int
    latest_confirmed_canonical_id: str | None
    latest_confirmed_canonical_version: int | None
    divergence_chain_id: str
    risk_cycle_id: str
    price_relation: str
    local_rsi_delta: float
    anchor_rsi_delta: float
    warning_evidence: str
    is_warmup: bool
    is_display_range: bool


def build_warning_events(
    *,
    symbol: str,
    sources: Iterable[Mapping[str, object]],
) -> list[WarningEvent]:
    """Build deterministic Phase 1 OPENED/REFRESHED audit events."""

    normalized: list[_WarningSource] = []
    for source in sources:
        if not _is_trigger(source):
            continue
        normalized.append(_normalize_source(symbol, source))

    unique: dict[tuple[str, int, str], _WarningSource] = {}
    for source in normalized:
        identity = (
            source.warning_id,
            source.source_version,
            source.decision_date,
        )
        previous = unique.get(identity)
        if previous is not None and previous != source:
            _raise_source_error(source, "conflicting evidence for warning event identity")
        unique[identity] = source

    grouped: dict[str, list[_WarningSource]] = {}
    for source in unique.values():
        grouped.setdefault(source.warning_id, []).append(source)

    events: list[WarningEvent] = []
    for warning_id in sorted(grouped):
        warning_sources = grouped[warning_id]
        version_dates: dict[int, str] = {}
        for source in warning_sources:
            previous_date = version_dates.get(source.source_version)
            if previous_date is not None and previous_date != source.decision_date:
                _raise_source_error(source, "same version on different dates")
            version_dates[source.source_version] = source.decision_date

        warning_sources.sort(
            key=lambda item: (item.decision_date, item.source_version)
        )
        previous_version: int | None = None
        for index, source in enumerate(warning_sources):
            if previous_version is not None and source.source_version <= previous_version:
                _raise_source_error(source, "version regression by decision_date")
            lifecycle_event = (
                WarningLifecycleEvent.OPENED
                if index == 0
                else WarningLifecycleEvent.REFRESHED
            )
            events.append(_build_event(source, lifecycle_event))
            previous_version = source.source_version

    events.sort(key=lambda event: (
        event.decision_date,
        event.warning_id,
        event.lifecycle_event.value,
        event.source_version,
    ))
    return events


def warning_events_frame(events: Iterable[WarningEvent]) -> pd.DataFrame:
    """Serialize warning events with a fixed schema, including when empty."""

    rows = []
    for event in events:
        row = {column: getattr(event, column) for column in WARNING_EVENT_COLUMNS}
        for column in (
            "warning_type",
            "lifecycle_event",
            "warning_status",
            "source_kind",
            "position_effect",
        ):
            row[column] = row[column].value
        rows.append(row)
    frame = pd.DataFrame(rows, columns=WARNING_EVENT_COLUMNS)
    if not frame.empty:
        frame.sort_values(
            ["decision_date", "warning_id", "lifecycle_event", "source_version"],
            kind="mergesort",
            inplace=True,
        )
        frame.reset_index(drop=True, inplace=True)
    return frame


def _is_trigger(source: Mapping[str, object]) -> bool:
    return (
        source.get("signal_type") == "DIVERGENCE_FORMING"
        and source.get("signal_status") == "FORMING"
        and source.get("price_relation") in TRIGGER_PRICE_RELATIONS
    )


def _normalize_source(
    symbol: str,
    source: Mapping[str, object],
) -> _WarningSource:
    _require(symbol, source, str(symbol).strip() != "", "symbol is nonempty")
    source_peak_id = _required_text(
        symbol, source, "candidate_peak_id", "source_peak_id"
    )
    source_version = _required_version(
        symbol, source, "canonical_version", "source_version"
    )
    source_peak_date = _required_date(
        symbol, source, "current_peak_date", "source_peak_date"
    )
    decision_date = _required_date(
        symbol, source, "decision_date", "decision_date"
    )
    momentum_anchor_id = _required_text(
        symbol, source, "momentum_anchor_canonical_id", "momentum_anchor_id"
    )
    momentum_anchor_version = _required_version(
        symbol,
        source,
        "momentum_anchor_canonical_version",
        "momentum_anchor_version",
    )
    last_structural_peak_id = _required_text(
        symbol,
        source,
        "previous_canonical_peak_id",
        "last_structural_peak_id",
    )
    last_structural_peak_version = _required_version(
        symbol,
        source,
        "previous_canonical_version",
        "last_structural_peak_version",
    )
    divergence_chain_id = _required_text(
        symbol, source, "divergence_chain_id", "divergence_chain_id"
    )
    risk_cycle_id = _required_text(
        symbol, source, "risk_cycle_id", "risk_cycle_id"
    )
    local_rsi_delta = _required_delta(
        symbol, source, "local_rsi_delta"
    )
    anchor_rsi_delta = _required_delta(
        symbol, source, "anchor_rsi_delta"
    )
    _require(
        symbol,
        source,
        "structural_eligible" in source
        and bool(source["structural_eligible"]) is False,
        "structural_eligible is False",
    )
    _require(
        symbol,
        source,
        "position_eligible" in source
        and bool(source["position_eligible"]) is False,
        "position_eligible is False",
    )
    _require(
        symbol,
        source,
        "pending_action_type" in source
        and source["pending_action_type"] is None,
        "pending_action_type is None",
    )

    latest_id_value = source.get("latest_confirmed_canonical_id")
    latest_confirmed_canonical_id = (
        None if latest_id_value is None else str(latest_id_value)
    )
    latest_version_value = source.get("latest_confirmed_canonical_version")
    latest_confirmed_canonical_version = (
        None
        if latest_version_value is None
        else _version_value(
            symbol,
            source,
            latest_version_value,
            "latest_confirmed_canonical_version",
        )
    )
    warning_id = _stable_id("FWARN-", {
        "symbol": symbol,
        "warning_type": WarningType.FORMING_DIVERGENCE_WARNING.value,
        "source_forming_peak_id": source_peak_id,
        "divergence_chain_id": divergence_chain_id,
        "momentum_anchor_id": momentum_anchor_id,
        "momentum_anchor_version": momentum_anchor_version,
        "last_structural_peak_id": last_structural_peak_id,
        "last_structural_peak_version": last_structural_peak_version,
    })
    price_relation = str(source["price_relation"])
    warning_evidence = _canonical_json({
        "source_signal_type": "DIVERGENCE_FORMING",
        "source_signal_status": "FORMING",
        "source_peak_id": source_peak_id,
        "source_version": source_version,
        "source_peak_date": source_peak_date,
        "price_relation": price_relation,
        "local_rsi_delta": local_rsi_delta,
        "anchor_rsi_delta": anchor_rsi_delta,
    })
    return _WarningSource(
        symbol=symbol,
        warning_id=warning_id,
        source_peak_id=source_peak_id,
        source_version=source_version,
        source_peak_date=source_peak_date,
        decision_date=decision_date,
        momentum_anchor_id=momentum_anchor_id,
        momentum_anchor_version=momentum_anchor_version,
        last_structural_peak_id=last_structural_peak_id,
        last_structural_peak_version=last_structural_peak_version,
        latest_confirmed_canonical_id=latest_confirmed_canonical_id,
        latest_confirmed_canonical_version=latest_confirmed_canonical_version,
        divergence_chain_id=divergence_chain_id,
        risk_cycle_id=risk_cycle_id,
        price_relation=price_relation,
        local_rsi_delta=local_rsi_delta,
        anchor_rsi_delta=anchor_rsi_delta,
        warning_evidence=warning_evidence,
        is_warmup=bool(source.get("is_warmup", False)),
        is_display_range=bool(source.get("is_display_range", False)),
    )


def _build_event(
    source: _WarningSource,
    lifecycle_event: WarningLifecycleEvent,
) -> WarningEvent:
    warning_event_id = _stable_id("WEVT-", {
        "warning_id": source.warning_id,
        "lifecycle_event": lifecycle_event.value,
        "source_version": source.source_version,
        "decision_date": source.decision_date,
    })
    return WarningEvent(
        symbol=source.symbol,
        warning_event_id=warning_event_id,
        warning_id=source.warning_id,
        warning_type=WarningType.FORMING_DIVERGENCE_WARNING,
        lifecycle_event=lifecycle_event,
        warning_status=WarningStatus.ACTIVE,
        source_kind=WarningSourceKind.FORMING_PEAK,
        source_peak_id=source.source_peak_id,
        source_version=source.source_version,
        source_canonical_peak_id=None,
        source_canonical_version=None,
        source_peak_date=source.source_peak_date,
        observation_date=source.decision_date,
        decision_date=source.decision_date,
        available_date=source.decision_date,
        momentum_anchor_id=source.momentum_anchor_id,
        momentum_anchor_version=source.momentum_anchor_version,
        last_structural_peak_id=source.last_structural_peak_id,
        last_structural_peak_version=source.last_structural_peak_version,
        latest_confirmed_canonical_id=source.latest_confirmed_canonical_id,
        latest_confirmed_canonical_version=source.latest_confirmed_canonical_version,
        divergence_chain_id=source.divergence_chain_id,
        risk_cycle_id=source.risk_cycle_id,
        price_relation=source.price_relation,
        local_rsi_delta=source.local_rsi_delta,
        anchor_rsi_delta=source.anchor_rsi_delta,
        warning_reason=(
            "FORMING_DIVERGENCE_OPENED"
            if lifecycle_event == WarningLifecycleEvent.OPENED
            else "FORMING_DIVERGENCE_REFRESHED"
        ),
        warning_evidence=source.warning_evidence,
        end_reason=None,
        linked_formal_signal_ref=None,
        position_effect=WarningPositionEffect.NONE,
        recommended_position_cap=None,
        is_warmup=source.is_warmup,
        is_display_range=source.is_display_range,
    )


def _required_text(
    symbol: str,
    source: Mapping[str, object],
    key: str,
    assertion_name: str,
) -> str:
    value = source.get(key)
    _require(
        symbol,
        source,
        value is not None and str(value).strip() != "",
        f"{assertion_name} is nonempty",
    )
    return str(value)


def _required_version(
    symbol: str,
    source: Mapping[str, object],
    key: str,
    assertion_name: str,
) -> int:
    value = source.get(key)
    _require(
        symbol,
        source,
        value is not None and str(value).strip() != "",
        f"{assertion_name} is nonempty",
    )
    return _version_value(symbol, source, value, assertion_name)


def _version_value(
    symbol: str,
    source: Mapping[str, object],
    value: object,
    assertion_name: str,
) -> int:
    try:
        version = int(value)  # type: ignore[arg-type]
        exact = not isinstance(value, float) or value.is_integer()
    except (TypeError, ValueError, OverflowError):
        version, exact = 0, False
    _require(
        symbol,
        source,
        not isinstance(value, bool) and exact and version > 0,
        f"{assertion_name} is a positive integer",
    )
    return version


def _required_date(
    symbol: str,
    source: Mapping[str, object],
    key: str,
    assertion_name: str,
) -> str:
    value = source.get(key)
    _require(
        symbol,
        source,
        value is not None and str(value).strip() != "",
        f"{assertion_name} is nonempty",
    )
    try:
        date = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        _raise_contract_error(symbol, source, f"{assertion_name} is a valid date")
    if pd.isna(date):
        _raise_contract_error(symbol, source, f"{assertion_name} is a valid date")
    return date.strftime("%Y-%m-%d")


def _required_delta(
    symbol: str,
    source: Mapping[str, object],
    key: str,
) -> float:
    try:
        value = float(source.get(key))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        _raise_contract_error(symbol, source, f"{key} is numeric")
    _require(symbol, source, math.isfinite(value), f"{key} is finite")
    _require(symbol, source, value <= -1.0, f"{key} <= -1.0")
    return value


def _require(
    symbol: str,
    source: Mapping[str, object],
    condition: bool,
    assertion: str,
) -> None:
    if not condition:
        _raise_contract_error(symbol, source, assertion)


def _raise_contract_error(
    symbol: str,
    source: Mapping[str, object],
    assertion: str,
) -> None:
    raise WarningSourceContractError(
        f"symbol={symbol} "
        f"source_peak_id={source.get('candidate_peak_id', '<missing>')} "
        f"source_version={source.get('canonical_version', '<missing>')}: "
        f"{assertion}"
    )


def _raise_source_error(source: _WarningSource, assertion: str) -> None:
    raise WarningSourceContractError(
        f"symbol={source.symbol} source_peak_id={source.source_peak_id} "
        f"source_version={source.source_version}: {assertion}"
    )


def _stable_id(prefix: str, payload: dict[str, object]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}{digest.upper()}"


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
