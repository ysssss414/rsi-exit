from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable, Mapping

import pandas as pd

from rsi_exit.models import (
    WarningEndReason,
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


class WarningLifecycleContractError(ValueError):
    """Warning lifecycle facts or event history violate the contract."""


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
        establishment_risk_cycle_id = warning_sources[0].risk_cycle_id
        previous_version: int | None = None
        for index, source in enumerate(warning_sources):
            if previous_version is not None and source.source_version <= previous_version:
                _raise_source_error(source, "version regression by decision_date")
            lifecycle_event = (
                WarningLifecycleEvent.OPENED
                if index == 0
                else WarningLifecycleEvent.REFRESHED
            )
            events.append(_build_event(
                source,
                lifecycle_event,
                establishment_risk_cycle_id=establishment_risk_cycle_id,
            ))
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
    for column in (
        "source_canonical_version",
        "latest_confirmed_canonical_version",
    ):
        frame[column] = pd.array(frame[column], dtype="Int64")
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

    (
        latest_confirmed_canonical_id,
        latest_confirmed_canonical_version,
    ) = _optional_latest_canonical_pair(
        symbol,
        source,
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
    *,
    establishment_risk_cycle_id: str,
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
        risk_cycle_id=establishment_risk_cycle_id,
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
    if not pd.api.types.is_scalar(value) or _is_missing_scalar(value):
        _raise_contract_error(symbol, source, f"{assertion_name} is nonempty text")
    text = str(value).strip()
    if not text:
        _raise_contract_error(symbol, source, f"{assertion_name} is nonempty text")
    return text


def _optional_latest_canonical_pair(
    symbol: str,
    source: Mapping[str, object],
) -> tuple[str | None, int | None]:
    assertion = (
        "latest_confirmed_canonical_id/version are both null or both valid"
    )
    canonical_id = source.get("latest_confirmed_canonical_id")
    canonical_version = source.get("latest_confirmed_canonical_version")
    if not pd.api.types.is_scalar(canonical_id) or not pd.api.types.is_scalar(
        canonical_version
    ):
        _raise_contract_error(symbol, source, assertion)
    id_missing = _is_missing_scalar(canonical_id)
    version_missing = _is_missing_scalar(canonical_version)
    if id_missing and version_missing:
        return None, None
    version = _positive_version(canonical_version)
    if id_missing or version_missing or version is None:
        _raise_contract_error(symbol, source, assertion)
    canonical_id_text = str(canonical_id).strip()
    if not canonical_id_text:
        _raise_contract_error(symbol, source, assertion)
    return canonical_id_text, version


def _is_missing_scalar(value: object) -> bool:
    if value is None:
        return True
    if not pd.api.types.is_scalar(value):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


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
        pd.api.types.is_scalar(value) and not _is_missing_scalar(value),
        f"{assertion_name} is nonempty",
    )
    return _version_value(symbol, source, value, assertion_name)


def _version_value(
    symbol: str,
    source: Mapping[str, object],
    value: object,
    assertion_name: str,
) -> int:
    version = _positive_version(value)
    _require(
        symbol,
        source,
        version is not None,
        f"{assertion_name} is a positive integer",
    )
    return version


def _positive_version(value: object) -> int | None:
    try:
        version = int(value)  # type: ignore[arg-type]
        exact = math.isfinite(float(value)) and float(value) == version
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, bool) or not exact or version <= 0:
        return None
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


@dataclass(frozen=True)
class _LifecycleFormingFact:
    source: _WarningSource
    current_peak_close: float
    current_peak_rsi: float


@dataclass(frozen=True)
class _FormalWarningFact:
    symbol: str
    decision_date: str
    signal_type: str
    signal_status: str
    structural_eligible: bool
    current_peak_date: str
    current_canonical_peak_id: str
    current_canonical_version: int
    previous_canonical_peak_id: str
    previous_canonical_version: int
    momentum_anchor_canonical_id: str
    momentum_anchor_canonical_version: int
    divergence_chain_id: str
    position_eligible: bool
    reset_reason: str | None
    same_canonical_anchor_breakout: bool
    latest_confirmed_canonical_id: str | None
    latest_confirmed_canonical_version: int | None
    is_warmup: bool
    is_display_range: bool
    formal_ref: str


@dataclass(frozen=True)
class _DailyWarningFact:
    symbol: str
    date: str
    close: float | None
    rsi: float | None
    is_warmup: bool
    is_display_range: bool


@dataclass(frozen=True)
class _ActiveWarning:
    symbol: str
    warning_id: str
    opened_observation_date: str
    source_peak_id: str
    source_version: int
    source_peak_date: str
    latest_decision_date: str
    current_peak_close: float
    current_peak_rsi: float
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


class WarningTracker:
    """Independent append-only tracker for one symbol's warning history."""

    def __init__(self, *, symbol: str) -> None:
        self.symbol = str(symbol)
        self.events: list[WarningEvent] = []
        self._active: dict[str, _ActiveWarning] = {}
        self._terminal: set[str] = set()
        self._events_by_id: dict[str, WarningEvent] = {}
        self._consumed_formal_refs: set[str] = set()
        self._deep_reset_streaks: dict[str, int] = {}

    def _append(self, event: WarningEvent) -> bool:
        previous = self._events_by_id.get(event.warning_event_id)
        if previous is not None:
            if previous != event:
                raise WarningLifecycleContractError(
                    "conflicting warning event identity: "
                    f"{event.warning_event_id}"
                )
            return False
        self._events_by_id[event.warning_event_id] = event
        self.events.append(event)
        return True

    def _open(
        self,
        event: WarningEvent,
        fact: _LifecycleFormingFact,
    ) -> None:
        if event.warning_id in self._terminal:
            return
        if event.warning_id in self._active:
            raise WarningLifecycleContractError(
                f"warning {event.warning_id} opened more than once"
            )
        self._append(event)
        self._active[event.warning_id] = _active_from_opened(event, fact)
        self._deep_reset_streaks[event.warning_id] = 0

    def _refresh(
        self,
        event: WarningEvent,
        fact: _LifecycleFormingFact,
    ) -> None:
        active = self._active.get(event.warning_id)
        if active is None:
            return
        if event.source_version <= active.source_version:
            raise WarningLifecycleContractError(
                f"warning {event.warning_id} has non-increasing refresh version"
            )
        self._append(event)
        self._active[event.warning_id] = _active_from_refresh(
            active,
            event,
            fact,
        )

    def _terminate(
        self,
        event: WarningEvent,
        *,
        formal_ref: str | None = None,
    ) -> None:
        if event.warning_id not in self._active:
            return
        if formal_ref is not None:
            if formal_ref in self._consumed_formal_refs:
                raise WarningLifecycleContractError(
                    f"formal signal ref consumed more than once: {formal_ref}"
                )
            self._consumed_formal_refs.add(formal_ref)
        self._append(event)
        self._active.pop(event.warning_id)
        self._deep_reset_streaks.pop(event.warning_id, None)
        self._terminal.add(event.warning_id)


def build_warning_lifecycle_events(
    *,
    symbol: str,
    forming_sources: Iterable[Mapping[str, object]],
    formal_sources: Iterable[Mapping[str, object]],
    daily_sources: Iterable[Mapping[str, object]],
    deep_reset_rsi_level: float,
    deep_reset_consecutive_days: int,
    extreme_reset_rsi_level: float,
) -> list[WarningEvent]:
    """Build Phase 1 events plus deterministic terminal lifecycle events."""

    symbol_text = str(symbol).strip()
    if not symbol_text:
        raise WarningLifecycleContractError("symbol is nonempty")
    deep_level = _finite_lifecycle_number(
        deep_reset_rsi_level,
        "deep_reset_rsi_level",
    )
    extreme_level = _finite_lifecycle_number(
        extreme_reset_rsi_level,
        "extreme_reset_rsi_level",
    )
    try:
        consecutive_days = int(deep_reset_consecutive_days)
    except (TypeError, ValueError, OverflowError) as exc:
        raise WarningLifecycleContractError(
            "deep_reset_consecutive_days is a positive integer"
        ) from exc
    if (
        isinstance(deep_reset_consecutive_days, bool)
        or consecutive_days <= 0
        or float(deep_reset_consecutive_days) != consecutive_days
    ):
        raise WarningLifecycleContractError(
            "deep_reset_consecutive_days is a positive integer"
        )

    forming_input = list(forming_sources)
    phase1_events = build_warning_events(
        symbol=symbol_text,
        sources=forming_input,
    )
    forming_facts = _normalize_forming_facts(symbol_text, forming_input)
    phase1_by_date: dict[str, list[WarningEvent]] = {}
    for event in phase1_events:
        fact_identity = _forming_fact_identity(event)
        if fact_identity not in forming_facts:
            raise WarningLifecycleContractError(
                f"missing lifecycle forming fact for {event.warning_event_id}"
            )
        phase1_by_date.setdefault(event.decision_date, []).append(event)

    formals = _normalize_formal_facts(formal_sources)
    formal_by_date: dict[str, list[_FormalWarningFact]] = {}
    for fact in formals:
        formal_by_date.setdefault(fact.decision_date, []).append(fact)
    daily = _normalize_daily_facts(daily_sources)
    daily_by_date = {fact.date: fact for fact in daily}

    dates = sorted(
        set(phase1_by_date) | set(formal_by_date) | set(daily_by_date)
    )
    tracker = WarningTracker(symbol=symbol_text)
    for decision_date in dates:
        forming_today = phase1_by_date.get(decision_date, [])
        forming_by_warning: dict[str, list[WarningEvent]] = {}
        for event in forming_today:
            forming_by_warning.setdefault(event.warning_id, []).append(event)
        for warning_id, events in forming_by_warning.items():
            if len(events) > 1:
                raise WarningLifecycleContractError(
                    f"warning {warning_id} has multiple forming events on "
                    f"{decision_date}"
                )

        formal_today = formal_by_date.get(decision_date, [])
        daily_today = daily_by_date.get(decision_date)
        active_before = list(tracker._active.values())
        divergence_matches = _match_formals(
            active_before,
            formal_today,
            _is_divergence_match,
            label="formal divergence",
        )
        clear_matches = _match_formals(
            active_before,
            formal_today,
            _is_clear_match,
            label="anchor breakout",
        )

        for active in sorted(active_before, key=lambda item: item.warning_id):
            current = tracker._active.get(active.warning_id)
            if current is None:
                continue
            deep_trigger: tuple[int, str] | None = None
            if (
                daily_today is not None
                and daily_today.symbol == current.symbol
                and daily_today.date > current.opened_observation_date
            ):
                streak = tracker._deep_reset_streaks[current.warning_id]
                if daily_today.rsi is None or daily_today.rsi >= deep_level:
                    streak = 0
                else:
                    streak += 1
                tracker._deep_reset_streaks[current.warning_id] = streak
                if daily_today.rsi is not None:
                    if daily_today.rsi <= extreme_level:
                        deep_trigger = (streak, "EXTREME_RSI")
                    elif streak >= consecutive_days:
                        deep_trigger = (streak, "CONSECUTIVE_DAYS")

            divergence = divergence_matches.get(current.warning_id)
            if divergence is not None:
                terminal = _build_formal_terminal_event(
                    current,
                    divergence,
                    lifecycle_event=WarningLifecycleEvent.ESCALATED,
                    status=WarningStatus.ESCALATED,
                    end_reason=WarningEndReason.FORMAL_DIVERGENCE_CONFIRMED,
                )
                tracker._terminate(terminal, formal_ref=divergence.formal_ref)
                continue

            clear = clear_matches.get(current.warning_id)
            if clear is not None:
                terminal = _build_formal_terminal_event(
                    current,
                    clear,
                    lifecycle_event=WarningLifecycleEvent.CLEARED,
                    status=WarningStatus.CLEARED,
                    end_reason=WarningEndReason.MOMENTUM_ANCHOR_REBUILT,
                )
                tracker._terminate(terminal, formal_ref=clear.formal_ref)
                continue

            refreshes = forming_by_warning.get(current.warning_id, [])
            if refreshes:
                refresh = refreshes[0]
                tracker._refresh(
                    refresh,
                    forming_facts[_forming_fact_identity(refresh)],
                )
                continue

            if (
                daily_today is None
                or daily_today.symbol != current.symbol
                or daily_today.date <= current.latest_decision_date
            ):
                continue

            comparison = _forming_comparison(current, daily_today)
            if comparison == "DOWN_DOWN":
                confirmations = [
                    fact
                    for fact in formal_today
                    if _is_confirmation_match(fact, current)
                ]
                if len(confirmations) > 1:
                    raise WarningLifecycleContractError(
                        "multiple confirmation facts match warning "
                        f"{current.warning_id} on {decision_date}"
                    )
                if confirmations:
                    confirmation = confirmations[0]
                    reason = _confirmation_end_reason(confirmation.signal_type)
                    terminal = _build_formal_terminal_event(
                        current,
                        confirmation,
                        lifecycle_event=WarningLifecycleEvent.INVALIDATED,
                        status=WarningStatus.INVALIDATED,
                        end_reason=reason,
                        daily=daily_today,
                    )
                    tracker._terminate(
                        terminal,
                        formal_ref=confirmation.formal_ref,
                    )
                    continue

            if deep_trigger is not None:
                streak, trigger_type = deep_trigger
                terminal = _build_daily_terminal_event(
                    current,
                    daily_today,
                    end_reason=WarningEndReason.DEEP_RSI_RESET_COMPLETED,
                    evidence={
                        "below_level": deep_level,
                        "consecutive_days": consecutive_days,
                        "current_streak": streak,
                        "daily_rsi": daily_today.rsi,
                        "extreme_level": extreme_level,
                        "trigger_type": trigger_type,
                    },
                )
                tracker._terminate(terminal)
                continue

            if comparison is not None:
                terminal = _build_daily_terminal_event(
                    current,
                    daily_today,
                    end_reason=WarningEndReason.FORMING_CONDITION_BROKEN,
                    evidence={
                        "comparison_result": comparison,
                        "current_close": daily_today.close,
                        "current_rsi": daily_today.rsi,
                        "latest_forming_close": current.current_peak_close,
                        "latest_forming_rsi": current.current_peak_rsi,
                    },
                )
                tracker._terminate(terminal)

        for event in sorted(
            forming_today,
            key=lambda item: (item.warning_id, item.source_version),
        ):
            if event.lifecycle_event != WarningLifecycleEvent.OPENED:
                continue
            if event.warning_id in tracker._active or event.warning_id in tracker._terminal:
                continue
            tracker._open(event, forming_facts[_forming_fact_identity(event)])

    tracker.events.sort(key=lambda event: (
        event.decision_date,
        event.warning_id,
        event.lifecycle_event.value,
        event.source_version,
    ))
    return tracker.events


def derive_warning_states(
    events: Iterable[WarningEvent],
    *,
    as_of_date: str | None = None,
) -> dict[str, WarningStatus]:
    """Derive warning states solely from an append-only event history."""

    cutoff = None
    if as_of_date is not None:
        cutoff = _lifecycle_date(as_of_date, "as_of_date")
    unique: dict[str, WarningEvent] = {}
    for event in events:
        event_date = _lifecycle_date(
            event.decision_date,
            "warning event decision_date",
        )
        if cutoff is not None and event_date > cutoff:
            continue
        previous = unique.get(event.warning_event_id)
        if previous is not None and previous != event:
            raise WarningLifecycleContractError(
                "conflicting warning event identity: "
                f"{event.warning_event_id}"
            )
        unique[event.warning_event_id] = event

    grouped: dict[str, list[WarningEvent]] = {}
    for event in unique.values():
        grouped.setdefault(event.warning_id, []).append(event)
    states: dict[str, WarningStatus] = {}
    terminal_events = {
        WarningLifecycleEvent.ESCALATED: WarningStatus.ESCALATED,
        WarningLifecycleEvent.CLEARED: WarningStatus.CLEARED,
        WarningLifecycleEvent.INVALIDATED: WarningStatus.INVALIDATED,
    }
    for warning_id in sorted(grouped):
        history = sorted(grouped[warning_id], key=lambda event: (
            _lifecycle_date(event.decision_date, "warning event decision_date"),
            event.lifecycle_event.value,
            event.source_version,
        ))
        state: WarningStatus | None = None
        terminal = False
        previous_date: str | None = None
        previous_version: int | None = None
        for index, event in enumerate(history):
            event_date = _lifecycle_date(
                event.decision_date,
                "warning event decision_date",
            )
            if terminal:
                raise WarningLifecycleContractError(
                    f"warning {warning_id} has an event after terminal state"
                )
            if previous_date is not None and event_date <= previous_date:
                raise WarningLifecycleContractError(
                    f"warning {warning_id} event dates are not increasing"
                )
            if index == 0:
                if (
                    event.lifecycle_event != WarningLifecycleEvent.OPENED
                    or event.warning_status != WarningStatus.ACTIVE
                ):
                    raise WarningLifecycleContractError(
                        f"warning {warning_id} does not start with OPENED"
                    )
                state = WarningStatus.ACTIVE
                previous_date = event_date
                previous_version = event.source_version
                continue
            if event.lifecycle_event == WarningLifecycleEvent.REFRESHED:
                if (
                    event.warning_status != WarningStatus.ACTIVE
                    or previous_version is None
                    or event.source_version <= previous_version
                ):
                    raise WarningLifecycleContractError(
                        f"warning {warning_id} has invalid REFRESHED event"
                    )
                state = WarningStatus.ACTIVE
                previous_date = event_date
                previous_version = event.source_version
                continue
            expected = terminal_events.get(event.lifecycle_event)
            if (
                expected is None
                or event.warning_status != expected
                or event.source_version != previous_version
            ):
                raise WarningLifecycleContractError(
                    f"warning {warning_id} has invalid lifecycle transition"
                )
            state = expected
            terminal = True
            previous_date = event_date
        if state is not None:
            states[warning_id] = state
    return states


def _normalize_forming_facts(
    symbol: str,
    sources: Iterable[Mapping[str, object]],
) -> dict[tuple[str, int, str], _LifecycleFormingFact]:
    facts: dict[tuple[str, int, str], _LifecycleFormingFact] = {}
    for raw in sources:
        if not _is_trigger(raw):
            continue
        source = _normalize_source(symbol, raw)
        close = _required_lifecycle_finite(
            raw.get("current_peak_close"),
            "current_peak_close",
            source.warning_id,
        )
        rsi = _required_lifecycle_finite(
            raw.get("current_peak_rsi"),
            "current_peak_rsi",
            source.warning_id,
        )
        identity = (
            source.warning_id,
            source.source_version,
            source.decision_date,
        )
        fact = _LifecycleFormingFact(
            source=source,
            current_peak_close=close,
            current_peak_rsi=rsi,
        )
        previous = facts.get(identity)
        if previous is not None and previous != fact:
            raise WarningLifecycleContractError(
                f"conflicting lifecycle forming evidence for {identity}"
            )
        facts[identity] = fact
    return facts


def _forming_fact_identity(event: WarningEvent) -> tuple[str, int, str]:
    return event.warning_id, event.source_version, event.decision_date


def _normalize_formal_facts(
    sources: Iterable[Mapping[str, object]],
) -> list[_FormalWarningFact]:
    unique: dict[str, _FormalWarningFact] = {}
    for source in sources:
        if source.get("signal_status") != "FORMAL":
            continue
        symbol = _lifecycle_text(source.get("symbol"), "formal symbol")
        decision_date = _lifecycle_date(
            source.get("decision_date"),
            "formal decision_date",
        )
        signal_type = _lifecycle_text(
            source.get("signal_type"),
            "formal signal_type",
        )
        current_peak_date = _lifecycle_date(
            source.get("current_peak_date"),
            "formal current_peak_date",
        )
        current_id, current_version = _required_lifecycle_pair(
            source,
            "current_canonical_peak_id",
            "current_canonical_version",
            "formal current canonical",
        )
        previous_id, previous_version = _required_lifecycle_pair(
            source,
            "previous_canonical_peak_id",
            "previous_canonical_version",
            "formal previous canonical",
        )
        anchor_id, anchor_version = _required_lifecycle_pair(
            source,
            "momentum_anchor_canonical_id",
            "momentum_anchor_canonical_version",
            "formal momentum anchor",
        )
        latest_id, latest_version = _optional_lifecycle_pair(
            source,
            "latest_confirmed_canonical_id",
            "latest_confirmed_canonical_version",
            "formal latest confirmed canonical",
        )
        chain_id = _lifecycle_text(
            source.get("divergence_chain_id"),
            "formal divergence_chain_id",
        )
        reset_value = source.get("reset_reason")
        reset_reason = None
        if not _is_missing_scalar(reset_value):
            reset_reason = _lifecycle_text(reset_value, "formal reset_reason")
        formal_ref = (
            f"{symbol}|{signal_type}|{current_id}@v{current_version}|"
            f"{decision_date}|{chain_id}"
        )
        fact = _FormalWarningFact(
            symbol=symbol,
            decision_date=decision_date,
            signal_type=signal_type,
            signal_status="FORMAL",
            structural_eligible=bool(source.get("structural_eligible", False)),
            current_peak_date=current_peak_date,
            current_canonical_peak_id=current_id,
            current_canonical_version=current_version,
            previous_canonical_peak_id=previous_id,
            previous_canonical_version=previous_version,
            momentum_anchor_canonical_id=anchor_id,
            momentum_anchor_canonical_version=anchor_version,
            divergence_chain_id=chain_id,
            position_eligible=bool(source.get("position_eligible", False)),
            reset_reason=reset_reason,
            same_canonical_anchor_breakout=bool(
                source.get("same_canonical_anchor_breakout", False)
            ),
            latest_confirmed_canonical_id=latest_id,
            latest_confirmed_canonical_version=latest_version,
            is_warmup=bool(source.get("is_warmup", False)),
            is_display_range=bool(source.get("is_display_range", False)),
            formal_ref=formal_ref,
        )
        previous = unique.get(formal_ref)
        if previous is not None and previous != fact:
            raise WarningLifecycleContractError(
                f"conflicting formal signal ref: {formal_ref}"
            )
        unique[formal_ref] = fact
    return sorted(unique.values(), key=lambda fact: (
        fact.decision_date,
        fact.formal_ref,
    ))


def _normalize_daily_facts(
    sources: Iterable[Mapping[str, object]],
) -> list[_DailyWarningFact]:
    facts: list[_DailyWarningFact] = []
    previous_date: str | None = None
    for source in sources:
        date = _lifecycle_date(source.get("date"), "daily date")
        if previous_date is not None and date <= previous_date:
            raise WarningLifecycleContractError(
                "daily dates must be unique and strictly increasing"
            )
        previous_date = date
        facts.append(_DailyWarningFact(
            symbol=_lifecycle_text(source.get("symbol"), "daily symbol"),
            date=date,
            close=_optional_lifecycle_finite(source.get("close"), "daily close"),
            rsi=_optional_lifecycle_finite(source.get("rsi"), "daily rsi"),
            is_warmup=bool(source.get("is_warmup", False)),
            is_display_range=bool(source.get("is_display_range", False)),
        ))
    return facts


def _active_from_opened(
    event: WarningEvent,
    fact: _LifecycleFormingFact,
) -> _ActiveWarning:
    return _ActiveWarning(
        symbol=event.symbol,
        warning_id=event.warning_id,
        opened_observation_date=event.observation_date,
        source_peak_id=event.source_peak_id,
        source_version=event.source_version,
        source_peak_date=event.source_peak_date,
        latest_decision_date=event.decision_date,
        current_peak_close=fact.current_peak_close,
        current_peak_rsi=fact.current_peak_rsi,
        momentum_anchor_id=event.momentum_anchor_id,
        momentum_anchor_version=event.momentum_anchor_version,
        last_structural_peak_id=event.last_structural_peak_id,
        last_structural_peak_version=event.last_structural_peak_version,
        latest_confirmed_canonical_id=event.latest_confirmed_canonical_id,
        latest_confirmed_canonical_version=(
            event.latest_confirmed_canonical_version
        ),
        divergence_chain_id=event.divergence_chain_id,
        risk_cycle_id=event.risk_cycle_id,
        price_relation=event.price_relation,
        local_rsi_delta=event.local_rsi_delta,
        anchor_rsi_delta=event.anchor_rsi_delta,
    )


def _active_from_refresh(
    active: _ActiveWarning,
    event: WarningEvent,
    fact: _LifecycleFormingFact,
) -> _ActiveWarning:
    return _ActiveWarning(
        symbol=active.symbol,
        warning_id=active.warning_id,
        opened_observation_date=active.opened_observation_date,
        source_peak_id=event.source_peak_id,
        source_version=event.source_version,
        source_peak_date=event.source_peak_date,
        latest_decision_date=event.decision_date,
        current_peak_close=fact.current_peak_close,
        current_peak_rsi=fact.current_peak_rsi,
        momentum_anchor_id=active.momentum_anchor_id,
        momentum_anchor_version=active.momentum_anchor_version,
        last_structural_peak_id=active.last_structural_peak_id,
        last_structural_peak_version=active.last_structural_peak_version,
        latest_confirmed_canonical_id=(
            event.latest_confirmed_canonical_id
        ),
        latest_confirmed_canonical_version=(
            event.latest_confirmed_canonical_version
        ),
        divergence_chain_id=active.divergence_chain_id,
        risk_cycle_id=active.risk_cycle_id,
        price_relation=event.price_relation,
        local_rsi_delta=event.local_rsi_delta,
        anchor_rsi_delta=event.anchor_rsi_delta,
    )


def _match_formals(
    active: list[_ActiveWarning],
    facts: list[_FormalWarningFact],
    matcher: object,
    *,
    label: str,
) -> dict[str, _FormalWarningFact]:
    matches: dict[str, list[_FormalWarningFact]] = {
        warning.warning_id: [] for warning in active
    }
    fact_warnings: dict[str, list[str]] = {}
    for warning in active:
        for fact in facts:
            if matcher(fact, warning):  # type: ignore[operator]
                matches[warning.warning_id].append(fact)
                fact_warnings.setdefault(fact.formal_ref, []).append(
                    warning.warning_id
                )
    for formal_ref, warning_ids in fact_warnings.items():
        if len(warning_ids) > 1:
            raise WarningLifecycleContractError(
                f"{label} {formal_ref} matches multiple active warnings"
            )
    selected: dict[str, _FormalWarningFact] = {}
    for warning_id, warning_matches in matches.items():
        if len(warning_matches) > 1:
            raise WarningLifecycleContractError(
                f"multiple {label} facts match warning {warning_id}"
            )
        if warning_matches:
            selected[warning_id] = warning_matches[0]
    return selected


def _is_divergence_match(
    fact: _FormalWarningFact,
    warning: _ActiveWarning,
) -> bool:
    return (
        fact.symbol == warning.symbol
        and fact.signal_status == "FORMAL"
        and fact.signal_type in {
            "NEW_HIGH_BEARISH_DIVERGENCE",
            "NEAR_HIGH_BEARISH_DIVERGENCE",
        }
        and fact.structural_eligible
        and fact.current_peak_date == warning.source_peak_date
        and fact.previous_canonical_peak_id == warning.last_structural_peak_id
        and fact.previous_canonical_version == warning.last_structural_peak_version
        and fact.momentum_anchor_canonical_id == warning.momentum_anchor_id
        and fact.momentum_anchor_canonical_version == warning.momentum_anchor_version
        and fact.divergence_chain_id == warning.divergence_chain_id
        and warning.latest_decision_date < fact.decision_date
    )


def _is_clear_match(
    fact: _FormalWarningFact,
    warning: _ActiveWarning,
) -> bool:
    return (
        fact.symbol == warning.symbol
        and fact.signal_status == "FORMAL"
        and fact.structural_eligible
        and fact.reset_reason == "ANCHOR_RSI_BREAKOUT"
        and fact.current_peak_date == warning.source_peak_date
        and fact.previous_canonical_peak_id == warning.last_structural_peak_id
        and fact.previous_canonical_version == warning.last_structural_peak_version
        and warning.latest_decision_date < fact.decision_date
        and fact.current_canonical_peak_id
        == fact.latest_confirmed_canonical_id
        and fact.current_canonical_version
        == fact.latest_confirmed_canonical_version
    )


def _is_confirmation_match(
    fact: _FormalWarningFact,
    warning: _ActiveWarning,
) -> bool:
    if fact.signal_type not in {
        "STRUCTURAL_PEAK_WITHOUT_DIVERGENCE",
        "INTRADAY_POTENTIAL_RETEST",
        "NON_COMPARABLE_PEAK",
    }:
        return False
    if (
        fact.signal_type == "STRUCTURAL_PEAK_WITHOUT_DIVERGENCE"
        and not fact.structural_eligible
    ):
        return False
    return (
        fact.symbol == warning.symbol
        and fact.signal_status == "FORMAL"
        and fact.current_peak_date == warning.source_peak_date
        and fact.previous_canonical_peak_id == warning.last_structural_peak_id
        and fact.previous_canonical_version == warning.last_structural_peak_version
        and fact.momentum_anchor_canonical_id == warning.momentum_anchor_id
        and fact.momentum_anchor_canonical_version == warning.momentum_anchor_version
        and fact.divergence_chain_id == warning.divergence_chain_id
        and warning.latest_decision_date < fact.decision_date
    )


def _confirmation_end_reason(signal_type: str) -> WarningEndReason:
    reasons = {
        "STRUCTURAL_PEAK_WITHOUT_DIVERGENCE": (
            WarningEndReason.CONFIRMED_WITHOUT_FORMAL_DIVERGENCE
        ),
        "INTRADAY_POTENTIAL_RETEST": WarningEndReason.INTRADAY_RETEST_ONLY,
        "NON_COMPARABLE_PEAK": WarningEndReason.NON_COMPARABLE_CONFIRMATION,
    }
    return reasons[signal_type]


def _forming_comparison(
    warning: _ActiveWarning,
    daily: _DailyWarningFact,
) -> str | None:
    if daily.close is None or daily.rsi is None:
        return None
    close_relation = (
        "UP" if daily.close > warning.current_peak_close
        else "DOWN" if daily.close < warning.current_peak_close
        else "EQUAL"
    )
    rsi_relation = (
        "UP" if daily.rsi > warning.current_peak_rsi
        else "DOWN" if daily.rsi < warning.current_peak_rsi
        else "EQUAL"
    )
    return f"{close_relation}_{rsi_relation}"


def _build_formal_terminal_event(
    warning: _ActiveWarning,
    formal: _FormalWarningFact,
    *,
    lifecycle_event: WarningLifecycleEvent,
    status: WarningStatus,
    end_reason: WarningEndReason,
    daily: _DailyWarningFact | None = None,
) -> WarningEvent:
    if lifecycle_event == WarningLifecycleEvent.ESCALATED:
        evidence = {
            "formal_canonical_id": formal.current_canonical_peak_id,
            "formal_canonical_version": formal.current_canonical_version,
            "formal_decision_date": formal.decision_date,
            "formal_signal_ref": formal.formal_ref,
            "formal_signal_type": formal.signal_type,
        }
        linked_ref: str | None = formal.formal_ref
    elif lifecycle_event == WarningLifecycleEvent.CLEARED:
        evidence = {
            "formal_canonical_id": formal.current_canonical_peak_id,
            "formal_canonical_version": formal.current_canonical_version,
            "formal_decision_date": formal.decision_date,
            "latest_lineage_id": formal.latest_confirmed_canonical_id,
            "latest_lineage_version": formal.latest_confirmed_canonical_version,
            "reset_reason": formal.reset_reason,
        }
        linked_ref = None
    else:
        if daily is None:
            raise WarningLifecycleContractError(
                "confirmed invalidation requires a daily comparison fact"
            )
        evidence = {
            "comparison_result": _forming_comparison(warning, daily),
            "current_close": daily.close,
            "current_rsi": daily.rsi,
            "latest_forming_close": warning.current_peak_close,
            "latest_forming_rsi": warning.current_peak_rsi,
            "matching_confirmation_type": formal.signal_type,
        }
        linked_ref = None
    return _build_terminal_event(
        warning,
        decision_date=formal.decision_date,
        lifecycle_event=lifecycle_event,
        status=status,
        source_kind=WarningSourceKind.FORMAL_SIGNAL,
        end_reason=end_reason,
        evidence=evidence,
        source_canonical_peak_id=formal.current_canonical_peak_id,
        source_canonical_version=formal.current_canonical_version,
        latest_confirmed_canonical_id=formal.latest_confirmed_canonical_id,
        latest_confirmed_canonical_version=(
            formal.latest_confirmed_canonical_version
        ),
        linked_formal_signal_ref=linked_ref,
        is_warmup=formal.is_warmup,
        is_display_range=formal.is_display_range,
    )


def _build_daily_terminal_event(
    warning: _ActiveWarning,
    daily: _DailyWarningFact,
    *,
    end_reason: WarningEndReason,
    evidence: dict[str, object],
) -> WarningEvent:
    return _build_terminal_event(
        warning,
        decision_date=daily.date,
        lifecycle_event=WarningLifecycleEvent.INVALIDATED,
        status=WarningStatus.INVALIDATED,
        source_kind=WarningSourceKind.DAILY_RSI,
        end_reason=end_reason,
        evidence=evidence,
        source_canonical_peak_id=None,
        source_canonical_version=None,
        latest_confirmed_canonical_id=(
            warning.latest_confirmed_canonical_id
        ),
        latest_confirmed_canonical_version=(
            warning.latest_confirmed_canonical_version
        ),
        linked_formal_signal_ref=None,
        is_warmup=daily.is_warmup,
        is_display_range=daily.is_display_range,
    )


def _build_terminal_event(
    warning: _ActiveWarning,
    *,
    decision_date: str,
    lifecycle_event: WarningLifecycleEvent,
    status: WarningStatus,
    source_kind: WarningSourceKind,
    end_reason: WarningEndReason,
    evidence: dict[str, object],
    source_canonical_peak_id: str | None,
    source_canonical_version: int | None,
    latest_confirmed_canonical_id: str | None,
    latest_confirmed_canonical_version: int | None,
    linked_formal_signal_ref: str | None,
    is_warmup: bool,
    is_display_range: bool,
) -> WarningEvent:
    warning_event_id = _stable_id("WEVT-", {
        "warning_id": warning.warning_id,
        "lifecycle_event": lifecycle_event.value,
        "source_version": warning.source_version,
        "decision_date": decision_date,
    })
    reason_by_lifecycle = {
        WarningLifecycleEvent.ESCALATED: "FORMING_DIVERGENCE_ESCALATED",
        WarningLifecycleEvent.CLEARED: "FORMING_DIVERGENCE_CLEARED",
        WarningLifecycleEvent.INVALIDATED: "FORMING_DIVERGENCE_INVALIDATED",
    }
    return WarningEvent(
        symbol=warning.symbol,
        warning_event_id=warning_event_id,
        warning_id=warning.warning_id,
        warning_type=WarningType.FORMING_DIVERGENCE_WARNING,
        lifecycle_event=lifecycle_event,
        warning_status=status,
        source_kind=source_kind,
        source_peak_id=warning.source_peak_id,
        source_version=warning.source_version,
        source_canonical_peak_id=source_canonical_peak_id,
        source_canonical_version=source_canonical_version,
        source_peak_date=warning.source_peak_date,
        observation_date=decision_date,
        decision_date=decision_date,
        available_date=decision_date,
        momentum_anchor_id=warning.momentum_anchor_id,
        momentum_anchor_version=warning.momentum_anchor_version,
        last_structural_peak_id=warning.last_structural_peak_id,
        last_structural_peak_version=warning.last_structural_peak_version,
        latest_confirmed_canonical_id=latest_confirmed_canonical_id,
        latest_confirmed_canonical_version=latest_confirmed_canonical_version,
        divergence_chain_id=warning.divergence_chain_id,
        risk_cycle_id=warning.risk_cycle_id,
        price_relation=warning.price_relation,
        local_rsi_delta=warning.local_rsi_delta,
        anchor_rsi_delta=warning.anchor_rsi_delta,
        warning_reason=reason_by_lifecycle[lifecycle_event],
        warning_evidence=_canonical_json(evidence),
        end_reason=end_reason.value,
        linked_formal_signal_ref=linked_formal_signal_ref,
        position_effect=WarningPositionEffect.NONE,
        recommended_position_cap=None,
        is_warmup=is_warmup,
        is_display_range=is_display_range,
    )


def _required_lifecycle_pair(
    source: Mapping[str, object],
    id_key: str,
    version_key: str,
    label: str,
) -> tuple[str, int]:
    canonical_id = _lifecycle_text(source.get(id_key), f"{label} id")
    version = _lifecycle_version(source.get(version_key), f"{label} version")
    return canonical_id, version


def _optional_lifecycle_pair(
    source: Mapping[str, object],
    id_key: str,
    version_key: str,
    label: str,
) -> tuple[str | None, int | None]:
    canonical_id = source.get(id_key)
    version = source.get(version_key)
    id_missing = _is_missing_scalar(canonical_id)
    version_missing = _is_missing_scalar(version)
    if id_missing and version_missing:
        return None, None
    if id_missing or version_missing:
        raise WarningLifecycleContractError(
            f"{label} id/version must both be null or both valid"
        )
    return (
        _lifecycle_text(canonical_id, f"{label} id"),
        _lifecycle_version(version, f"{label} version"),
    )


def _lifecycle_text(value: object, label: str) -> str:
    if not pd.api.types.is_scalar(value) or _is_missing_scalar(value):
        raise WarningLifecycleContractError(f"{label} is nonempty text")
    text = str(value).strip()
    if not text:
        raise WarningLifecycleContractError(f"{label} is nonempty text")
    return text


def _lifecycle_version(value: object, label: str) -> int:
    version = _positive_version(value)
    if version is None:
        raise WarningLifecycleContractError(f"{label} is a positive integer")
    return version


def _lifecycle_date(value: object, label: str) -> str:
    if value is None or str(value).strip() == "":
        raise WarningLifecycleContractError(f"{label} is a valid date")
    try:
        date = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise WarningLifecycleContractError(f"{label} is a valid date") from exc
    if pd.isna(date):
        raise WarningLifecycleContractError(f"{label} is a valid date")
    return date.strftime("%Y-%m-%d")


def _finite_lifecycle_number(value: object, label: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise WarningLifecycleContractError(f"{label} is finite") from exc
    if not math.isfinite(number):
        raise WarningLifecycleContractError(f"{label} is finite")
    return number


def _required_lifecycle_finite(
    value: object,
    label: str,
    warning_id: str,
) -> float:
    try:
        return _finite_lifecycle_number(value, label)
    except WarningLifecycleContractError as exc:
        raise WarningLifecycleContractError(
            f"warning {warning_id}: {label} is finite"
        ) from exc


def _optional_lifecycle_finite(value: object, label: str) -> float | None:
    if _is_missing_scalar(value):
        return None
    return _finite_lifecycle_number(value, label)
