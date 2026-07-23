from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class BaseState(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    S0_MAIN_TREND = "S0_MAIN_TREND"
    S1_STRONG_PULLBACK = "S1_STRONG_PULLBACK"
    S2_RISK_DOWNGRADE = "S2_RISK_DOWNGRADE"
    S3_EXIT = "S3_EXIT"
    S4_REPAIR_WATCH = "S4_REPAIR_WATCH"
    # Kept only so v0.1 readers do not fail on historical CSV values.  v0.2
    # never transitions into this state: re-entry qualification is an event.
    S5_RESTRENGTHEN = "S5_RESTRENGTHEN"


class SignalType(str, Enum):
    TREND_STRENGTHENING = "TREND_STRENGTHENING"
    BEARISH_DIVERGENCE = "BEARISH_DIVERGENCE"
    LOWER_HIGH_WEAK_REBOUND = "LOWER_HIGH_WEAK_REBOUND"
    LOWER_PRICE_RSI_FLAT = "LOWER_PRICE_RSI_FLAT"
    LOWER_PRICE_RSI_IMPROVING = "LOWER_PRICE_RSI_IMPROVING"
    NEW_HIGH_BEARISH_DIVERGENCE = "NEW_HIGH_BEARISH_DIVERGENCE"
    NEAR_HIGH_BEARISH_DIVERGENCE = "NEAR_HIGH_BEARISH_DIVERGENCE"
    STRUCTURAL_PEAK_WITHOUT_DIVERGENCE = "STRUCTURAL_PEAK_WITHOUT_DIVERGENCE"
    INTRADAY_POTENTIAL_RETEST = "INTRADAY_POTENTIAL_RETEST"
    NON_COMPARABLE_PEAK = "NON_COMPARABLE_PEAK"
    DIVERGENCE_FORMING = "DIVERGENCE_FORMING"


class WarningType(str, Enum):
    FORMING_DIVERGENCE_WARNING = "FORMING_DIVERGENCE_WARNING"


class WarningLifecycleEvent(str, Enum):
    OPENED = "OPENED"
    REFRESHED = "REFRESHED"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"
    INVALIDATED = "INVALIDATED"


class WarningStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"
    INVALIDATED = "INVALIDATED"


class WarningSourceKind(str, Enum):
    FORMING_PEAK = "FORMING_PEAK"


class WarningPositionEffect(str, Enum):
    NONE = "NONE"


@dataclass(frozen=True)
class WarningEvent:
    symbol: str
    warning_event_id: str
    warning_id: str
    warning_type: WarningType
    lifecycle_event: WarningLifecycleEvent
    warning_status: WarningStatus
    source_kind: WarningSourceKind
    source_peak_id: str
    source_version: int
    source_canonical_peak_id: str | None
    source_canonical_version: int | None
    source_peak_date: str
    observation_date: str
    decision_date: str
    available_date: str
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
    warning_reason: str
    warning_evidence: str
    end_reason: str | None
    linked_formal_signal_ref: str | None
    position_effect: WarningPositionEffect
    recommended_position_cap: float | None
    is_warmup: bool
    is_display_range: bool


@dataclass
class Peak:
    """One immutable confirmed candidate.

    ``peak_id`` is a v0.1 compatibility alias for ``candidate_peak_id``.  All
    v0.2 relationships use the explicit candidate/canonical fields.
    """

    peak_id: str
    peak_index: int
    peak_date: pd.Timestamp
    confirm_index: int
    confirm_date: pd.Timestamp
    earliest_action_date: pd.Timestamp | pd.NaT
    peak_close: float
    peak_rsi: float
    confirm_close: float
    confirm_rsi: float
    days_from_previous_peak: int | None
    interim_min_close: float | None
    interim_min_rsi: float | None
    price_retrace_pct: float | None
    rsi_retrace: float | None
    is_independent_peak: bool
    merged_into_peak_id: str | None
    previous_peak_id: str | None
    momentum_anchor_peak_id: str | None = None
    canonical_updated: bool = False
    candidate_peak_id: str | None = None
    canonical_peak_id: str | None = None
    representative_candidate_id: str | None = None
    canonical_version: int = 1
    previous_candidate_peak_id: str | None = None
    previous_canonical_peak_id: str | None = None
    cycle_id: str | None = None
    is_warmup: bool = False
    is_display_range: bool = True
    peak_high: float | None = None
    previous_day_close: float | None = None
    peak_layer: str = "CANDIDATE_PEAK"
    canonical_status: str = "CONFIRMED_CANONICAL_PEAK"
    structural_eligible: bool = False

    def __post_init__(self) -> None:
        if self.candidate_peak_id is None:
            self.candidate_peak_id = self.peak_id
        if self.canonical_peak_id is None:
            self.canonical_peak_id = self.merged_into_peak_id or self.peak_id
        if self.representative_candidate_id is None:
            self.representative_candidate_id = self.candidate_peak_id


@dataclass
class CanonicalPeak:
    canonical_peak_id: str
    representative_candidate_id: str
    canonical_version: int
    peak_index: int
    peak_date: pd.Timestamp
    confirm_index: int
    confirm_date: pd.Timestamp
    earliest_action_date: pd.Timestamp | pd.NaT
    peak_close: float
    peak_rsi: float
    confirm_close: float
    confirm_rsi: float
    days_from_previous_peak: int | None
    interim_min_close: float | None
    interim_min_rsi: float | None
    price_retrace_pct: float | None
    rsi_retrace: float | None
    previous_canonical_peak_id: str | None
    cycle_id: str | None = None
    peak_high: float | None = None
    previous_day_close: float | None = None
    canonical_status: str = "CONFIRMED_CANONICAL_PEAK"
    structural_eligible: bool = False

    @property
    def peak_id(self) -> str:
        """v0.1 read-only compatibility alias."""
        return self.canonical_peak_id


@dataclass
class PeakEvent:
    """Candidate and the canonical snapshot known on its confirmation date."""

    peak: Peak
    canonical: CanonicalPeak | None = None
    canonical_created: bool = False
    canonical_updated: bool = False


@dataclass(frozen=True)
class FormingPeakEvent:
    """Causal snapshot of a still-open potential canonical top."""

    forming_peak_id: str
    forming_version: int
    peak_index: int
    peak_date: pd.Timestamp
    peak_high: float
    peak_close: float
    peak_rsi: float
    previous_day_close: float


@dataclass
class DivergenceResult:
    candidate_peak_id: str
    canonical_peak_id: str
    canonical_version: int
    previous_candidate_peak_id: str
    previous_canonical_peak_id: str
    previous_canonical_version: int
    signal_type: SignalType
    price_relation: str
    rsi_relation: str
    divergence_count: int
    momentum_anchor_candidate_id: str
    momentum_anchor_canonical_id: str
    momentum_anchor_canonical_version: int
    momentum_anchor_date: pd.Timestamp
    momentum_anchor_close: float
    momentum_anchor_rsi: float
    price_vs_anchor_pct: float
    rsi_vs_anchor: float
    cycle_id: str
    reset_reason: str | None = None
    previous_peak_date: pd.Timestamp | None = None
    previous_peak_close: float | None = None
    previous_peak_rsi: float | None = None
    previous_peak_high: float | None = None
    previous_day_close: float | None = None
    comparable_zone_low: float | None = None
    comparable_zone_high: float | None = None
    local_rsi_delta: float | None = None
    anchor_rsi_delta: float | None = None
    structural_eligible: bool = False
    divergence_type: str | None = None
    divergence_index: int = 0
    signal_status: str = "FORMAL"
    chain_reset_reason: str | None = None
    divergence_chain_id: str | None = None
    risk_cycle_id: str | None = None
    position_eligible: bool = False
    close_rejected_from_high_zone: bool = False
    same_canonical_anchor_breakout: bool = False

    @property
    def peak_id(self) -> str:
        return self.candidate_peak_id

    @property
    def previous_peak_id(self) -> str:
        return self.previous_candidate_peak_id

    @property
    def momentum_anchor_peak_id(self) -> str:
        return self.momentum_anchor_candidate_id


@dataclass
class StateTransition:
    previous_state: BaseState
    current_state: BaseState
    trigger: str
    action: str
    position_cap: float
    state_event: str | None = None
    allow_reentry: bool = False
    reentry_qualification_date: pd.Timestamp | None = None
