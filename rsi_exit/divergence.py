from __future__ import annotations

from copy import deepcopy

from rsi_exit.models import DivergenceResult, Peak, SignalType


def classify_peak_pair(
    previous: Peak,
    current: Peak,
    *,
    price_tolerance_pct: float = 0.005,
    rsi_tolerance: float = 1.0,
) -> tuple[SignalType, str, str]:
    """Classify one adjacent effective-peak pair using exact v0.1 boundaries."""
    price_floor = previous.peak_close * (1 - price_tolerance_pct)
    price_near_or_higher = current.peak_close >= price_floor
    rsi_clearly_lower = current.peak_rsi < previous.peak_rsi - rsi_tolerance

    if current.peak_rsi >= previous.peak_rsi + rsi_tolerance:
        rsi_relation = "RSI_HIGHER"
    elif rsi_clearly_lower:
        rsi_relation = "RSI_LOWER"
    else:
        rsi_relation = "RSI_FLAT_WITHIN_TOLERANCE"
    price_relation = (
        "PRICE_NEW_OR_NEAR_HIGH" if price_near_or_higher else "PRICE_LOWER_HIGH"
    )

    if price_near_or_higher and not rsi_clearly_lower:
        signal_type = SignalType.TREND_STRENGTHENING
    elif price_near_or_higher:
        signal_type = SignalType.BEARISH_DIVERGENCE
    elif rsi_clearly_lower:
        signal_type = SignalType.LOWER_HIGH_WEAK_REBOUND
    else:
        signal_type = SignalType.LOWER_PRICE_RSI_IMPROVING
    return signal_type, price_relation, rsi_relation


class DivergenceTracker:
    def __init__(
        self,
        *,
        price_tolerance_pct: float = 0.005,
        rsi_tolerance: float = 1.0,
        max_peak_gap: int = 30,
        cycle_reset_rsi: float = 50.0,
    ) -> None:
        self.price_tolerance_pct = float(price_tolerance_pct)
        self.rsi_tolerance = float(rsi_tolerance)
        self.max_peak_gap = int(max_peak_gap)
        self.cycle_reset_rsi = float(cycle_reset_rsi)
        self.previous: Peak | None = None
        self.anchor: Peak | None = None
        self.divergence_count = 0

    def reset_cycle(self) -> None:
        self.previous = None
        self.anchor = None
        self.divergence_count = 0

    def process(self, peak: Peak) -> DivergenceResult | None:
        if not peak.is_independent_peak:
            self._apply_merged_update(peak)
            return None
        if self.previous is None:
            self.previous = deepcopy(peak)
            self.anchor = deepcopy(peak)
            self.divergence_count = 0
            return None

        previous = self.previous
        reset_reason: str | None = None
        if (
            peak.days_from_previous_peak is not None
            and peak.days_from_previous_peak > self.max_peak_gap
        ):
            reset_reason = "PEAK_GAP_EXCEEDED"
        elif (
            peak.interim_min_rsi is not None
            and peak.interim_min_rsi < self.cycle_reset_rsi
        ):
            reset_reason = "INTERIM_RSI_BELOW_RESET_LEVEL"

        signal_type, price_relation, rsi_relation = classify_peak_pair(
            previous,
            peak,
            price_tolerance_pct=self.price_tolerance_pct,
            rsi_tolerance=self.rsi_tolerance,
        )

        if reset_reason is not None:
            self.divergence_count = 0
            self.anchor = deepcopy(peak)
        elif signal_type == SignalType.TREND_STRENGTHENING:
            self.divergence_count = 0
            self.anchor = deepcopy(peak)
        elif signal_type == SignalType.BEARISH_DIVERGENCE:
            self.divergence_count += 1
        elif (
            signal_type == SignalType.LOWER_PRICE_RSI_IMPROVING
            and peak.peak_rsi >= previous.peak_rsi + self.rsi_tolerance
        ):
            self.divergence_count = 0
            self.anchor = deepcopy(peak)
            reset_reason = "RSI_PEAK_IMPROVED"

        if self.anchor is None or peak.peak_rsi > self.anchor.peak_rsi:
            self.anchor = deepcopy(peak)
        assert self.anchor is not None
        result = DivergenceResult(
            peak_id=peak.peak_id,
            previous_peak_id=previous.peak_id,
            signal_type=signal_type,
            price_relation=price_relation,
            rsi_relation=rsi_relation,
            divergence_count=self.divergence_count,
            momentum_anchor_peak_id=self.anchor.peak_id,
            momentum_anchor_date=self.anchor.peak_date,
            momentum_anchor_close=self.anchor.peak_close,
            momentum_anchor_rsi=self.anchor.peak_rsi,
            price_vs_anchor_pct=(
                peak.peak_close / self.anchor.peak_close - 1.0
                if self.anchor.peak_close
                else 0.0
            ),
            rsi_vs_anchor=peak.peak_rsi - self.anchor.peak_rsi,
            reset_reason=reset_reason,
            previous_peak_date=previous.peak_date,
            previous_peak_close=previous.peak_close,
            previous_peak_rsi=previous.peak_rsi,
        )
        self.previous = deepcopy(peak)
        return result

    def _apply_merged_update(self, peak: Peak) -> None:
        if not peak.canonical_updated or self.previous is None:
            return
        if peak.merged_into_peak_id != self.previous.peak_id:
            return
        canonical = deepcopy(peak)
        canonical.peak_id = self.previous.peak_id
        canonical.previous_peak_id = self.previous.previous_peak_id
        canonical.is_independent_peak = True
        canonical.merged_into_peak_id = None
        self.previous = canonical
        if self.anchor is not None and self.anchor.peak_id == canonical.peak_id:
            self.anchor = deepcopy(canonical)
