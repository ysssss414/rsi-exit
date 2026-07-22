from __future__ import annotations

import math

import pandas as pd

from rsi_exit.models import BaseState, StateTransition


DEFAULT_LEVELS = {"strong": 70.0, "life": 60.0, "neutral": 50.0, "weak": 40.0}
DEFAULT_CAPS = {
    "uninitialized": 0.0,
    "base_s0": 1.0,
    "base_s1": 1.0,
    "base_s2": 0.5,
    "base_s3": 0.0,
    "base_s4": 0.0,
}


class RsiExitStateMachine:
    def __init__(
        self,
        initial_state: BaseState = BaseState.UNINITIALIZED,
        *,
        levels: dict[str, float] | None = None,
        position_caps: dict[str, float] | None = None,
    ) -> None:
        self.state = initial_state
        self.levels = {**DEFAULT_LEVELS, **(levels or {})}
        self.caps = {**DEFAULT_CAPS, **(position_caps or {})}
        self.previous_rsi: float | None = None
        self.consecutive_below_life = 0

    def step(
        self,
        *,
        rsi: float,
        close: float,
        ma20: float,
        external_risk: int = 0,
        hard_exit: int = 0,
        decision_date: pd.Timestamp | None = None,
    ) -> StateTransition:
        previous_state = self.state
        if _missing(rsi) or _missing(ma20):
            action, cap = self._action_cap(self.state)
            return StateTransition(previous_state, self.state, "INDICATORS_UNAVAILABLE", action, cap)

        strong = float(self.levels["strong"])
        life = float(self.levels["life"])
        neutral = float(self.levels["neutral"])
        below_life = rsi < life
        self.consecutive_below_life = self.consecutive_below_life + 1 if below_life else 0
        below_ma20 = close < ma20
        above_ma20 = close > ma20
        state_event: str | None = None
        allow_reentry = False

        if hard_exit:
            state, trigger = BaseState.S3_EXIT, "HARD_EXIT"
        elif rsi < neutral:
            state, trigger = BaseState.S3_EXIT, "RSI_BELOW_NEUTRAL"
        elif below_life and below_ma20:
            state, trigger = BaseState.S3_EXIT, "RSI_BELOW_LIFE_AND_CLOSE_BELOW_MA"
        elif self.consecutive_below_life >= 2:
            state, trigger = BaseState.S3_EXIT, "RSI_BELOW_LIFE_TWO_DAYS"
        elif previous_state in {BaseState.S3_EXIT, BaseState.S4_REPAIR_WATCH}:
            if rsi >= strong and above_ma20:
                state, trigger = BaseState.S0_MAIN_TREND, "REENTRY_QUALIFIED"
                state_event, allow_reentry = "ALLOW_REENTRY", True
            elif life <= rsi < strong and above_ma20:
                state, trigger = BaseState.S4_REPAIR_WATCH, "REPAIR_WATCH"
            else:
                state, trigger = BaseState.S3_EXIT, "REPAIR_FAILED"
        elif rsi < strong and below_ma20 and external_risk:
            state, trigger = BaseState.S2_RISK_DOWNGRADE, "MA_BREAK_WITH_EXTERNAL_RISK"
        elif below_life:
            crossed = self.previous_rsi is None or self.previous_rsi >= life
            state = BaseState.S2_RISK_DOWNGRADE
            trigger = "RSI_FIRST_BREAK_BELOW_LIFE" if crossed else "RSI_REMAINS_BELOW_LIFE"
        elif rsi >= strong:
            state, trigger = BaseState.S0_MAIN_TREND, "RSI_AT_OR_ABOVE_STRONG"
        else:
            state, trigger = BaseState.S1_STRONG_PULLBACK, "RSI_LIFE_TO_STRONG"

        self.state = state
        self.previous_rsi = float(rsi)
        action, cap = self._action_cap(state)
        if allow_reentry:
            action = "ALLOW_REENTRY"
        return StateTransition(
            previous_state,
            state,
            trigger,
            action,
            cap,
            state_event=state_event,
            allow_reentry=allow_reentry,
            reentry_qualification_date=decision_date if allow_reentry else None,
        )

    def force_exit(self, trigger: str) -> StateTransition:
        previous = self.state
        self.state = BaseState.S3_EXIT
        action, cap = self._action_cap(self.state)
        return StateTransition(previous, self.state, trigger, action, cap)

    def _action_cap(self, state: BaseState) -> tuple[str, float]:
        mapping = {
            BaseState.UNINITIALIZED: ("WAIT_FOR_WARMUP", "uninitialized"),
            BaseState.S0_MAIN_TREND: ("HOLD", "base_s0"),
            BaseState.S1_STRONG_PULLBACK: ("HOLD_NO_ADD", "base_s1"),
            BaseState.S2_RISK_DOWNGRADE: ("REDUCE", "base_s2"),
            BaseState.S3_EXIT: ("EXIT", "base_s3"),
            BaseState.S4_REPAIR_WATCH: ("WATCH", "base_s4"),
            BaseState.S5_RESTRENGTHEN: ("HOLD", "base_s0"),
        }
        action, key = mapping[state]
        return action, float(self.caps[key])


def _missing(value: float) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))
