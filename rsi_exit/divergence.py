from __future__ import annotations

from copy import deepcopy
import re
from typing import Iterable

import pandas as pd

from rsi_exit.models import (
    CanonicalPeak,
    DivergenceResult,
    FormingPeakEvent,
    Peak,
    PeakEvent,
    SignalType,
)


STRICT_NEW_HIGH = "STRICT_NEW_HIGH"
FORMAL_NEAR_HIGH_RETEST = "FORMAL_NEAR_HIGH_RETEST"
INTRADAY_POTENTIAL_RETEST = "INTRADAY_POTENTIAL_RETEST"
NON_COMPARABLE_PEAK = "NON_COMPARABLE_PEAK"
STRUCTURAL_RELATIONS = {STRICT_NEW_HIGH, FORMAL_NEAR_HIGH_RETEST}
FORMAL_DIVERGENCES = {
    SignalType.NEW_HIGH_BEARISH_DIVERGENCE,
    SignalType.NEAR_HIGH_BEARISH_DIVERGENCE,
}


def _value(peak: Peak | CanonicalPeak, name: str):
    return getattr(peak, name)


def _high(peak: Peak | CanonicalPeak) -> float:
    value = getattr(peak, "peak_high", None)
    return float(_value(peak, "peak_close") if value is None else value)


def comparable_zone(previous: Peak | CanonicalPeak) -> tuple[float, float]:
    """Return the frozen previous-real-day-close/peak-close comparison zone."""
    peak_close = float(_value(previous, "peak_close"))
    previous_close = getattr(previous, "previous_day_close", None)
    previous_close = peak_close if previous_close is None else float(previous_close)
    return min(previous_close, peak_close), max(previous_close, peak_close)


def classify_price_relation(
    previous: Peak | CanonicalPeak,
    current: Peak | CanonicalPeak,
    *,
    price_epsilon: float = 1e-8,
) -> str:
    """Classify price in the required priority order, without economic tolerance."""
    zone_low, _ = comparable_zone(previous)
    current_high = _high(current)
    if current_high > _high(previous) + float(price_epsilon):
        return STRICT_NEW_HIGH
    if float(_value(current, "peak_close")) >= zone_low:
        return FORMAL_NEAR_HIGH_RETEST
    if current_high >= zone_low:
        return INTRADAY_POTENTIAL_RETEST
    return NON_COMPARABLE_PEAK


def rsi_relation(delta: float, *, tolerance: float = 1.0) -> str:
    if delta <= -float(tolerance):
        return "RSI_LOWER"
    if delta >= float(tolerance):
        return "RSI_HIGHER"
    return "RSI_FLAT_WITHIN_TOLERANCE"


def classify_peak_pair(
    previous: Peak | CanonicalPeak,
    current: Peak | CanonicalPeak,
    *,
    price_epsilon: float = 1e-8,
    divergence_rsi_tolerance: float = 1.0,
    price_tolerance_pct: float | None = None,
    rsi_tolerance: float | None = None,
) -> tuple[SignalType, str, str]:
    """Classify a pair locally; anchor validation belongs to ``DivergenceTracker``.

    The v0.2 keyword names remain accepted for source compatibility.  Percentage
    price tolerance is intentionally ignored because v0.3 forbids economic
    price buffers.
    """
    del price_tolerance_pct
    tolerance = (
        float(divergence_rsi_tolerance)
        if rsi_tolerance is None
        else float(rsi_tolerance)
    )
    price_relation = classify_price_relation(
        previous, current, price_epsilon=price_epsilon
    )
    delta = float(_value(current, "peak_rsi")) - float(_value(previous, "peak_rsi"))
    relation = rsi_relation(delta, tolerance=tolerance)
    if price_relation == STRICT_NEW_HIGH and delta <= -tolerance:
        signal_type = SignalType.NEW_HIGH_BEARISH_DIVERGENCE
    elif price_relation == FORMAL_NEAR_HIGH_RETEST and delta <= -tolerance:
        signal_type = SignalType.NEAR_HIGH_BEARISH_DIVERGENCE
    elif price_relation in STRUCTURAL_RELATIONS:
        signal_type = SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE
    elif price_relation == INTRADAY_POTENTIAL_RETEST:
        signal_type = SignalType.INTRADAY_POTENTIAL_RETEST
    else:
        signal_type = SignalType.NON_COMPARABLE_PEAK
    return signal_type, price_relation, relation


def deep_rsi_reset_reason(
    values: Iterable[float],
    *,
    below_level: float = 50.0,
    consecutive_days: int = 3,
    extreme_level: float = 40.0,
) -> str | None:
    """Evaluate strict-below streak and inclusive extreme boundary."""
    streak = 0
    minimum: float | None = None
    for raw in values:
        if pd.isna(raw):
            streak = 0
            continue
        value = float(raw)
        minimum = value if minimum is None else min(minimum, value)
        streak = streak + 1 if value < float(below_level) else 0
        if streak >= int(consecutive_days):
            return "DEEP_RSI_RESET"
    if minimum is not None and minimum <= float(extreme_level):
        return "DEEP_RSI_RESET"
    return None


class DivergenceTracker:
    """Track the v0.3 structural chain independently from risk cycles."""

    def __init__(
        self,
        *,
        price_epsilon: float = 1e-8,
        divergence_rsi_tolerance: float = 1.0,
        anchor_rsi_tolerance: float = 1.0,
        momentum_strengthening_tolerance: float = 1.0,
        anchor_reset_tolerance: float = 2.0,
        deep_reset_rsi_level: float = 50.0,
        deep_reset_consecutive_days: int = 3,
        extreme_reset_rsi_level: float = 40.0,
        max_structural_peak_gap: int = 28,
        rsi_values: Iterable[float] | None = None,
        cycle_id: str = "DCHAIN0001",
        # Accepted v0.2 names; none changes the v0.3 price rule.
        price_tolerance_pct: float | None = None,
        rsi_tolerance: float | None = None,
        max_peak_gap: int | None = None,
        cycle_reset_rsi: float | None = None,
    ) -> None:
        del price_tolerance_pct
        self.price_epsilon = float(price_epsilon)
        self.divergence_rsi_tolerance = float(
            divergence_rsi_tolerance if rsi_tolerance is None else rsi_tolerance
        )
        self.anchor_rsi_tolerance = float(anchor_rsi_tolerance)
        self.momentum_strengthening_tolerance = float(momentum_strengthening_tolerance)
        self.anchor_reset_tolerance = float(anchor_reset_tolerance)
        self.deep_reset_rsi_level = float(
            deep_reset_rsi_level if cycle_reset_rsi is None else cycle_reset_rsi
        )
        self.deep_reset_consecutive_days = int(deep_reset_consecutive_days)
        self.extreme_reset_rsi_level = float(extreme_reset_rsi_level)
        self.max_structural_peak_gap = int(
            max_structural_peak_gap if max_peak_gap is None else max_peak_gap
        )
        self.rsi_values = None if rsi_values is None else list(rsi_values)
        self.cycle_id = cycle_id
        self.previous: CanonicalPeak | None = None
        self.last_structural_peak: CanonicalPeak | None = None
        self.anchor: CanonicalPeak | None = None
        self.divergence_count = 0
        self._locked_canonical_ids: set[str] = set()

    @property
    def divergence_chain_id(self) -> str:
        return self.cycle_id

    def reset_cycle(
        self,
        cycle_id: str | None = None,
        *,
        baseline: CanonicalPeak | None = None,
    ) -> None:
        """Compatibility API for an explicit divergence-chain reset."""
        if cycle_id is not None:
            self.cycle_id = cycle_id
        self.previous = deepcopy(baseline)
        self.last_structural_peak = deepcopy(baseline)
        self.anchor = deepcopy(baseline)
        self.divergence_count = 0
        self._locked_canonical_ids = set()

    def process(
        self,
        event_or_peak: PeakEvent | Peak,
        *,
        risk_cycle_id: str | None = None,
    ) -> DivergenceResult | None:
        event = self._event(event_or_peak)
        candidate = event.peak
        canonical = event.canonical
        assert canonical is not None
        current = self._candidate_snapshot(event)

        if self.last_structural_peak is None:
            self._establish_initial(current)
            return None

        if not event.canonical_created and not event.canonical_updated:
            return None

        assert self.anchor is not None
        previous = deepcopy(self.last_structural_peak)
        anchor_before = deepcopy(self.anchor)
        self._locked_canonical_ids.add(previous.canonical_peak_id)
        self._locked_canonical_ids.add(current.canonical_peak_id)

        price_relation = classify_price_relation(
            previous, current, price_epsilon=self.price_epsilon
        )
        zone_low, zone_high = comparable_zone(previous)
        local_delta = current.peak_rsi - previous.peak_rsi
        anchor_delta = current.peak_rsi - anchor_before.peak_rsi
        relation = rsi_relation(
            local_delta, tolerance=self.divergence_rsi_tolerance
        )
        structural = price_relation in STRUCTURAL_RELATIONS

        if not structural:
            signal_type = (
                SignalType.INTRADAY_POTENTIAL_RETEST
                if price_relation == INTRADAY_POTENTIAL_RETEST
                else SignalType.NON_COMPARABLE_PEAK
            )
            return self._result(
                candidate_id=candidate.candidate_peak_id or candidate.peak_id,
                current=current,
                previous=previous,
                anchor=anchor_before,
                signal_type=signal_type,
                price_relation=price_relation,
                rsi_relation_value=relation,
                zone_low=zone_low,
                zone_high=zone_high,
                local_delta=local_delta,
                anchor_delta=anchor_delta,
                structural=False,
                risk_cycle_id=risk_cycle_id,
            )

        # Preserve v0.2.1 initial-anchor qualification for an extending
        # canonical cluster.  This may raise the anchor, but it is not an
        # anchor-breakout chain reset and never rewrites an emitted result.
        if event.canonical_updated and current.peak_rsi > anchor_before.peak_rsi:
            self.anchor = deepcopy(current)
            self.previous = deepcopy(current)
            self.last_structural_peak = deepcopy(current)
            return self._result(
                candidate_id=candidate.candidate_peak_id or candidate.peak_id,
                current=current,
                previous=previous,
                anchor=current,
                signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE,
                price_relation=price_relation,
                rsi_relation_value=relation,
                zone_low=zone_low,
                zone_high=zone_high,
                local_delta=local_delta,
                anchor_delta=anchor_delta,
                structural=True,
                risk_cycle_id=risk_cycle_id,
            )

        reset_reason = self._precomparison_reset(previous, current)
        if reset_reason is not None:
            self._close_chain_with(current)
            return self._result(
                candidate_id=candidate.candidate_peak_id or candidate.peak_id,
                current=current,
                previous=previous,
                anchor=self.anchor or current,
                signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE,
                price_relation=price_relation,
                rsi_relation_value=relation,
                zone_low=zone_low,
                zone_high=zone_high,
                local_delta=local_delta,
                anchor_delta=anchor_delta,
                structural=True,
                reset_reason=reset_reason,
                risk_cycle_id=risk_cycle_id,
            )

        if current.peak_rsi >= anchor_before.peak_rsi + self.anchor_reset_tolerance:
            self._close_chain_with(current)
            return self._result(
                candidate_id=candidate.candidate_peak_id or candidate.peak_id,
                current=current,
                previous=previous,
                anchor=self.anchor or current,
                signal_type=SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE,
                price_relation=price_relation,
                rsi_relation_value=relation,
                zone_low=zone_low,
                zone_high=zone_high,
                local_delta=local_delta,
                anchor_delta=anchor_delta,
                structural=True,
                reset_reason="ANCHOR_RSI_BREAKOUT",
                risk_cycle_id=risk_cycle_id,
            )

        local_weaker = local_delta <= -self.divergence_rsi_tolerance
        anchor_weaker = current.peak_rsi <= (
            anchor_before.peak_rsi - self.anchor_rsi_tolerance
        )
        if local_weaker and anchor_weaker:
            signal_type = (
                SignalType.NEW_HIGH_BEARISH_DIVERGENCE
                if price_relation == STRICT_NEW_HIGH
                else SignalType.NEAR_HIGH_BEARISH_DIVERGENCE
            )
            self.divergence_count += 1
            position_eligible = True
        else:
            signal_type = SignalType.STRUCTURAL_PEAK_WITHOUT_DIVERGENCE
            position_eligible = False

        self.previous = deepcopy(current)
        self.last_structural_peak = deepcopy(current)
        return self._result(
            candidate_id=candidate.candidate_peak_id or candidate.peak_id,
            current=current,
            previous=previous,
            anchor=anchor_before,
            signal_type=signal_type,
            price_relation=price_relation,
            rsi_relation_value=relation,
            zone_low=zone_low,
            zone_high=zone_high,
            local_delta=local_delta,
            anchor_delta=anchor_delta,
            structural=True,
            position_eligible=position_eligible,
            risk_cycle_id=risk_cycle_id,
        )

    def preview_forming(
        self,
        forming: FormingPeakEvent,
        *,
        risk_cycle_id: str | None = None,
    ) -> DivergenceResult | None:
        """Return a non-mutating forming event only when both RSI tests pass."""
        if self.last_structural_peak is None or self.anchor is None:
            return None
        current = CanonicalPeak(
            canonical_peak_id=forming.forming_peak_id,
            representative_candidate_id=forming.forming_peak_id,
            canonical_version=forming.forming_version,
            peak_index=forming.peak_index,
            peak_date=forming.peak_date,
            confirm_index=forming.peak_index,
            confirm_date=pd.NaT,
            earliest_action_date=pd.NaT,
            peak_close=forming.peak_close,
            peak_rsi=forming.peak_rsi,
            confirm_close=forming.peak_close,
            confirm_rsi=forming.peak_rsi,
            days_from_previous_peak=None,
            interim_min_close=None,
            interim_min_rsi=None,
            price_retrace_pct=None,
            rsi_retrace=None,
            previous_canonical_peak_id=self.last_structural_peak.canonical_peak_id,
            peak_high=forming.peak_high,
            previous_day_close=forming.previous_day_close,
            canonical_status="FORMING_CANONICAL_PEAK",
        )
        previous = deepcopy(self.last_structural_peak)
        anchor = deepcopy(self.anchor)
        price_relation = classify_price_relation(
            previous, current, price_epsilon=self.price_epsilon
        )
        if price_relation not in STRUCTURAL_RELATIONS:
            return None
        local_delta = current.peak_rsi - previous.peak_rsi
        anchor_delta = current.peak_rsi - anchor.peak_rsi
        if not (
            local_delta <= -self.divergence_rsi_tolerance
            and current.peak_rsi <= anchor.peak_rsi - self.anchor_rsi_tolerance
        ):
            return None
        zone_low, zone_high = comparable_zone(previous)
        return self._result(
            candidate_id=forming.forming_peak_id,
            current=current,
            previous=previous,
            anchor=anchor,
            signal_type=SignalType.DIVERGENCE_FORMING,
            price_relation=price_relation,
            rsi_relation_value=rsi_relation(
                local_delta, tolerance=self.divergence_rsi_tolerance
            ),
            zone_low=zone_low,
            zone_high=zone_high,
            local_delta=local_delta,
            anchor_delta=anchor_delta,
            structural=False,
            signal_status="FORMING",
            risk_cycle_id=risk_cycle_id,
        )

    def _precomparison_reset(
        self, previous: CanonicalPeak, current: CanonicalPeak
    ) -> str | None:
        gap = current.peak_index - previous.peak_index
        if gap > self.max_structural_peak_gap:
            return "STRUCTURAL_PEAK_GAP"
        between = self._rsi_between(previous, current)
        return deep_rsi_reset_reason(
            between,
            below_level=self.deep_reset_rsi_level,
            consecutive_days=self.deep_reset_consecutive_days,
            extreme_level=self.extreme_reset_rsi_level,
        )

    def _rsi_between(
        self, previous: CanonicalPeak, current: CanonicalPeak
    ) -> list[float]:
        if self.rsi_values is not None:
            start = max(0, previous.peak_index + 1)
            end = max(start, current.peak_index)
            return [float(value) for value in self.rsi_values[start:end]]
        if current.interim_min_rsi is None:
            return []
        return [float(current.interim_min_rsi)]

    def _establish_initial(self, current: CanonicalPeak) -> None:
        self.previous = deepcopy(current)
        self.last_structural_peak = deepcopy(current)
        self.anchor = deepcopy(current)

    def _close_chain_with(self, current: CanonicalPeak) -> None:
        self.cycle_id = self._next_chain_id(self.cycle_id)
        self.divergence_count = 0
        self.previous = deepcopy(current)
        self.last_structural_peak = deepcopy(current)
        self.anchor = deepcopy(current)

    @staticmethod
    def _next_chain_id(current: str) -> str:
        match = re.fullmatch(r"(.*?)(\d+)", current)
        if match is None:
            return f"{current}-NEXT"
        prefix, number = match.groups()
        return f"{prefix}{int(number) + 1:0{len(number)}d}"

    def _result(
        self,
        *,
        candidate_id: str,
        current: CanonicalPeak,
        previous: CanonicalPeak,
        anchor: CanonicalPeak,
        signal_type: SignalType,
        price_relation: str,
        rsi_relation_value: str,
        zone_low: float,
        zone_high: float,
        local_delta: float,
        anchor_delta: float,
        structural: bool,
        position_eligible: bool = False,
        reset_reason: str | None = None,
        signal_status: str = "FORMAL",
        risk_cycle_id: str | None = None,
    ) -> DivergenceResult:
        return DivergenceResult(
            candidate_peak_id=candidate_id,
            canonical_peak_id=current.canonical_peak_id,
            canonical_version=current.canonical_version,
            previous_candidate_peak_id=previous.representative_candidate_id,
            previous_canonical_peak_id=previous.canonical_peak_id,
            previous_canonical_version=previous.canonical_version,
            signal_type=signal_type,
            price_relation=price_relation,
            rsi_relation=rsi_relation_value,
            divergence_count=self.divergence_count,
            momentum_anchor_candidate_id=anchor.representative_candidate_id,
            momentum_anchor_canonical_id=anchor.canonical_peak_id,
            momentum_anchor_canonical_version=anchor.canonical_version,
            momentum_anchor_date=anchor.peak_date,
            momentum_anchor_close=anchor.peak_close,
            momentum_anchor_rsi=anchor.peak_rsi,
            price_vs_anchor_pct=(
                current.peak_close / anchor.peak_close - 1.0
                if anchor.peak_close else 0.0
            ),
            rsi_vs_anchor=current.peak_rsi - anchor.peak_rsi,
            cycle_id=risk_cycle_id or self.cycle_id,
            reset_reason=reset_reason,
            previous_peak_date=previous.peak_date,
            previous_peak_close=previous.peak_close,
            previous_peak_rsi=previous.peak_rsi,
            previous_peak_high=_high(previous),
            previous_day_close=previous.previous_day_close,
            comparable_zone_low=zone_low,
            comparable_zone_high=zone_high,
            local_rsi_delta=local_delta,
            anchor_rsi_delta=anchor_delta,
            structural_eligible=structural,
            divergence_type=signal_type.value,
            divergence_index=self.divergence_count,
            signal_status=signal_status,
            chain_reset_reason=reset_reason,
            divergence_chain_id=self.cycle_id,
            risk_cycle_id=risk_cycle_id,
            position_eligible=position_eligible,
            close_rejected_from_high_zone=(
                price_relation == STRICT_NEW_HIGH and current.peak_close < zone_low
            ),
        )

    @staticmethod
    def _candidate_snapshot(event: PeakEvent) -> CanonicalPeak:
        value = event.peak
        canonical = event.canonical
        assert canonical is not None
        return CanonicalPeak(
            canonical_peak_id=canonical.canonical_peak_id,
            representative_candidate_id=value.candidate_peak_id or value.peak_id,
            canonical_version=value.canonical_version,
            peak_index=value.peak_index,
            peak_date=value.peak_date,
            confirm_index=value.confirm_index,
            confirm_date=value.confirm_date,
            earliest_action_date=value.earliest_action_date,
            peak_close=value.peak_close,
            peak_rsi=value.peak_rsi,
            confirm_close=value.confirm_close,
            confirm_rsi=value.confirm_rsi,
            days_from_previous_peak=value.days_from_previous_peak,
            interim_min_close=value.interim_min_close,
            interim_min_rsi=value.interim_min_rsi,
            price_retrace_pct=value.price_retrace_pct,
            rsi_retrace=value.rsi_retrace,
            previous_canonical_peak_id=value.previous_canonical_peak_id,
            peak_high=value.peak_high,
            previous_day_close=value.previous_day_close,
            canonical_status="CONFIRMED_CANONICAL_PEAK",
        )

    @staticmethod
    def _event(value: PeakEvent | Peak) -> PeakEvent:
        if isinstance(value, PeakEvent):
            return value
        canonical = CanonicalPeak(
            canonical_peak_id=value.canonical_peak_id or value.merged_into_peak_id or value.peak_id,
            representative_candidate_id=value.representative_candidate_id or value.candidate_peak_id or value.peak_id,
            canonical_version=value.canonical_version,
            peak_index=value.peak_index,
            peak_date=value.peak_date,
            confirm_index=value.confirm_index,
            confirm_date=value.confirm_date,
            earliest_action_date=value.earliest_action_date,
            peak_close=value.peak_close,
            peak_rsi=value.peak_rsi,
            confirm_close=value.confirm_close,
            confirm_rsi=value.confirm_rsi,
            days_from_previous_peak=value.days_from_previous_peak,
            interim_min_close=value.interim_min_close,
            interim_min_rsi=value.interim_min_rsi,
            price_retrace_pct=value.price_retrace_pct,
            rsi_retrace=value.rsi_retrace,
            previous_canonical_peak_id=value.previous_canonical_peak_id or value.previous_peak_id,
            peak_high=value.peak_high,
            previous_day_close=value.previous_day_close,
        )
        return PeakEvent(
            value,
            canonical,
            bool(value.is_independent_peak),
            bool(value.canonical_updated),
        )
