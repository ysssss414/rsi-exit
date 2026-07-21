from __future__ import annotations

from rsi_exit.models import SignalType


def divergence_position_rule(
    signal_type: SignalType,
    divergence_count: int,
    confirm_rsi: float,
) -> tuple[str, float]:
    if signal_type == SignalType.BEARISH_DIVERGENCE:
        if divergence_count >= 3:
            return "EXIT_ON_THIRD_DIVERGENCE", 0.00
        if confirm_rsi < 60:
            return "REDUCE_TO_40", 0.40
        if divergence_count == 2:
            return "REDUCE_TO_40", 0.40
        if divergence_count == 1:
            return "REDUCE_TO_70", 0.70
        return "OBSERVE_RESET_DIVERGENCE", 1.00
    if signal_type == SignalType.LOWER_HIGH_WEAK_REBOUND:
        return ("REDUCE_TO_70", 0.70) if confirm_rsi >= 60 else ("REDUCE_TO_40", 0.40)
    return "NO_DIVERGENCE_REDUCTION", 1.00


def merge_position_caps(
    *,
    base_action: str,
    base_cap: float,
    signal_action: str | None,
    signal_cap: float | None,
) -> tuple[str, float]:
    if signal_cap is None or base_cap <= signal_cap:
        return base_action, float(base_cap)
    return str(signal_action), float(signal_cap)
