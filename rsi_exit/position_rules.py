from __future__ import annotations

from rsi_exit.models import SignalType


def divergence_position_rule(
    signal_type: SignalType,
    divergence_count: int,
    confirm_rsi: float,
    *,
    life_level: float = 60.0,
    position_caps: dict[str, float] | None = None,
) -> tuple[str, float]:
    caps = position_caps or {
        "first_divergence": 0.7,
        "second_divergence": 0.4,
        "third_divergence": 0.0,
        "divergence_below_life": 0.4,
        "weak_rebound_above_life": 0.7,
        "weak_rebound_below_life": 0.4,
    }
    if signal_type in {
        SignalType.BEARISH_DIVERGENCE,
        SignalType.NEW_HIGH_BEARISH_DIVERGENCE,
        SignalType.NEAR_HIGH_BEARISH_DIVERGENCE,
    }:
        if divergence_count >= 3:
            return "EXIT_ON_THIRD_DIVERGENCE", float(caps["third_divergence"])
        if confirm_rsi < life_level:
            return "REDUCE_ON_DIVERGENCE_BELOW_LIFE", float(caps["divergence_below_life"])
        if divergence_count == 2:
            return "REDUCE_ON_SECOND_DIVERGENCE", float(caps["second_divergence"])
        if divergence_count == 1:
            return "REDUCE_ON_FIRST_DIVERGENCE", float(caps["first_divergence"])
    if signal_type == SignalType.LOWER_HIGH_WEAK_REBOUND:
        key = "weak_rebound_above_life" if confirm_rsi >= life_level else "weak_rebound_below_life"
        return "REDUCE_ON_WEAK_REBOUND", float(caps[key])
    return "NO_DIVERGENCE_REDUCTION", 1.0


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
