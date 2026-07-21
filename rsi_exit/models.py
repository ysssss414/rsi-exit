from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class BaseState(str, Enum):
    S0_MAIN_TREND = "S0_MAIN_TREND"
    S1_STRONG_PULLBACK = "S1_STRONG_PULLBACK"
    S2_RISK_DOWNGRADE = "S2_RISK_DOWNGRADE"
    S3_EXIT = "S3_EXIT"
    S4_REPAIR_WATCH = "S4_REPAIR_WATCH"
    S5_RESTRENGTHEN = "S5_RESTRENGTHEN"


class SignalType(str, Enum):
    TREND_STRENGTHENING = "TREND_STRENGTHENING"
    BEARISH_DIVERGENCE = "BEARISH_DIVERGENCE"
    LOWER_HIGH_WEAK_REBOUND = "LOWER_HIGH_WEAK_REBOUND"
    LOWER_PRICE_RSI_IMPROVING = "LOWER_PRICE_RSI_IMPROVING"


@dataclass
class Peak:
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


@dataclass
class PeakEvent:
    """Canonical independent swing peak available only on confirm_date."""

    peak: Peak


@dataclass
class DivergenceResult:
    peak_id: str
    previous_peak_id: str
    signal_type: SignalType
    price_relation: str
    rsi_relation: str
    divergence_count: int
    momentum_anchor_peak_id: str
    momentum_anchor_date: pd.Timestamp
    momentum_anchor_close: float
    momentum_anchor_rsi: float
    price_vs_anchor_pct: float
    rsi_vs_anchor: float
    reset_reason: str | None = None
    previous_peak_date: pd.Timestamp | None = None
    previous_peak_close: float | None = None
    previous_peak_rsi: float | None = None


@dataclass
class StateTransition:
    previous_state: BaseState
    current_state: BaseState
    trigger: str
    action: str
    position_cap: float
