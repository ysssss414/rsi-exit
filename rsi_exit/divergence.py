from __future__ import annotations

from copy import deepcopy

from rsi_exit.models import CanonicalPeak, DivergenceResult, Peak, PeakEvent, SignalType


def _value(peak: Peak | CanonicalPeak, name: str):
    return getattr(peak, name)


def classify_peak_pair(
    previous: Peak | CanonicalPeak,
    current: Peak | CanonicalPeak,
    *,
    price_tolerance_pct: float = 0.005,
    rsi_tolerance: float = 1.0,
) -> tuple[SignalType, str, str]:
    """Classify adjacent canonical snapshots with closed lower RSI boundary."""
    price_floor = float(_value(previous, "peak_close")) * (1 - price_tolerance_pct)
    price_near_or_higher = float(_value(current, "peak_close")) >= price_floor
    rsi_delta = float(_value(current, "peak_rsi")) - float(_value(previous, "peak_rsi"))
    rsi_clearly_lower = rsi_delta <= -rsi_tolerance
    rsi_clearly_higher = rsi_delta >= rsi_tolerance

    if rsi_clearly_higher:
        rsi_relation = "RSI_HIGHER"
    elif rsi_clearly_lower:
        rsi_relation = "RSI_LOWER"
    else:
        rsi_relation = "RSI_FLAT_WITHIN_TOLERANCE"
    price_relation = "PRICE_NEW_OR_NEAR_HIGH" if price_near_or_higher else "PRICE_LOWER_HIGH"

    if price_near_or_higher and not rsi_clearly_lower:
        signal_type = SignalType.TREND_STRENGTHENING
    elif price_near_or_higher:
        signal_type = SignalType.BEARISH_DIVERGENCE
    elif rsi_clearly_lower:
        signal_type = SignalType.LOWER_HIGH_WEAK_REBOUND
    elif rsi_clearly_higher:
        signal_type = SignalType.LOWER_PRICE_RSI_IMPROVING
    else:
        signal_type = SignalType.LOWER_PRICE_RSI_FLAT
    return signal_type, price_relation, rsi_relation


class DivergenceTracker:
    def __init__(
        self,
        *,
        price_tolerance_pct: float = 0.005,
        rsi_tolerance: float = 1.0,
        max_peak_gap: int = 30,
        cycle_reset_rsi: float = 50.0,
        cycle_id: str = "CYCLE0001",
    ) -> None:
        self.price_tolerance_pct = float(price_tolerance_pct)
        self.rsi_tolerance = float(rsi_tolerance)
        self.max_peak_gap = int(max_peak_gap)
        self.cycle_reset_rsi = float(cycle_reset_rsi)
        self.cycle_id = cycle_id
        self.previous: CanonicalPeak | None = None
        self.anchor: CanonicalPeak | None = None
        self.divergence_count = 0

    def reset_cycle(
        self,
        cycle_id: str | None = None,
        *,
        baseline: CanonicalPeak | None = None,
    ) -> None:
        if cycle_id is not None:
            self.cycle_id = cycle_id
        self.previous = deepcopy(baseline)
        self.anchor = deepcopy(baseline)
        self.divergence_count = 0

    def process(self, event_or_peak: PeakEvent | Peak) -> DivergenceResult | None:
        event = self._event(event_or_peak)
        candidate = event.peak
        canonical = event.canonical
        assert canonical is not None
        canonical.cycle_id = self.cycle_id

        if self.previous is None:
            # Divergence cycles and detector waves intentionally have different
            # lifecycles.  A merged global candidate is still a valid first
            # baseline after a cycle reset, using that candidate's own values.
            baseline = deepcopy(canonical)
            baseline.representative_candidate_id = candidate.candidate_peak_id or candidate.peak_id
            for name in (
                "peak_index", "peak_date", "confirm_index", "confirm_date",
                "earliest_action_date", "peak_close", "peak_rsi", "confirm_close", "confirm_rsi",
                "days_from_previous_peak", "interim_min_close", "interim_min_rsi",
                "price_retrace_pct", "rsi_retrace",
            ):
                setattr(baseline, name, getattr(candidate, name))
            self.previous = baseline
            self._raise_anchor_only(baseline)
            return None

        if not event.canonical_created:
            if event.canonical_updated:
                if self.previous is not None and self.previous.canonical_peak_id == canonical.canonical_peak_id:
                    self.previous = deepcopy(canonical)
                self._raise_anchor_only(canonical)
            return None

        previous = deepcopy(self.previous)
        reset_reason: str | None = None
        if canonical.days_from_previous_peak is not None and canonical.days_from_previous_peak > self.max_peak_gap:
            reset_reason = "PEAK_GAP_EXCEEDED"
        elif canonical.interim_min_rsi is not None and canonical.interim_min_rsi < self.cycle_reset_rsi:
            reset_reason = "INTERIM_RSI_BELOW_RESET_LEVEL"

        signal_type, price_relation, rsi_relation = classify_peak_pair(
            previous,
            canonical,
            price_tolerance_pct=self.price_tolerance_pct,
            rsi_tolerance=self.rsi_tolerance,
        )
        if reset_reason is not None:
            self.divergence_count = 0
        elif signal_type == SignalType.TREND_STRENGTHENING:
            self.divergence_count = 0
            reset_reason = "TREND_STRENGTHENING"
        elif signal_type == SignalType.BEARISH_DIVERGENCE:
            self.divergence_count += 1
        elif signal_type == SignalType.LOWER_PRICE_RSI_IMPROVING:
            self.divergence_count = 0
            reset_reason = "RSI_PEAK_IMPROVED"

        self._raise_anchor_only(canonical)
        assert self.anchor is not None
        result = DivergenceResult(
            candidate_peak_id=candidate.candidate_peak_id or candidate.peak_id,
            canonical_peak_id=canonical.canonical_peak_id,
            canonical_version=canonical.canonical_version,
            previous_candidate_peak_id=previous.representative_candidate_id,
            previous_canonical_peak_id=previous.canonical_peak_id,
            previous_canonical_version=previous.canonical_version,
            signal_type=signal_type,
            price_relation=price_relation,
            rsi_relation=rsi_relation,
            divergence_count=self.divergence_count,
            momentum_anchor_candidate_id=self.anchor.representative_candidate_id,
            momentum_anchor_canonical_id=self.anchor.canonical_peak_id,
            momentum_anchor_canonical_version=self.anchor.canonical_version,
            momentum_anchor_date=self.anchor.peak_date,
            momentum_anchor_close=self.anchor.peak_close,
            momentum_anchor_rsi=self.anchor.peak_rsi,
            price_vs_anchor_pct=(canonical.peak_close / self.anchor.peak_close - 1.0) if self.anchor.peak_close else 0.0,
            rsi_vs_anchor=canonical.peak_rsi - self.anchor.peak_rsi,
            cycle_id=self.cycle_id,
            reset_reason=reset_reason,
            previous_peak_date=previous.peak_date,
            previous_peak_close=previous.peak_close,
            previous_peak_rsi=previous.peak_rsi,
        )
        self.previous = deepcopy(canonical)
        return result

    def _raise_anchor_only(self, canonical: CanonicalPeak) -> None:
        if self.anchor is None or canonical.peak_rsi > self.anchor.peak_rsi:
            self.anchor = deepcopy(canonical)

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
        )
        created = bool(value.is_independent_peak)
        return PeakEvent(value, canonical, created, bool(value.canonical_updated))
