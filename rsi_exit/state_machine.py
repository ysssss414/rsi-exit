from __future__ import annotations

import math

from rsi_exit.models import BaseState, StateTransition


STATE_ACTIONS: dict[BaseState, tuple[str, float]] = {
    BaseState.S0_MAIN_TREND: ("HOLD", 1.00),
    BaseState.S1_STRONG_PULLBACK: ("HOLD_NO_ADD", 1.00),
    BaseState.S2_RISK_DOWNGRADE: ("REDUCE", 0.50),
    BaseState.S3_EXIT: ("EXIT", 0.00),
    BaseState.S4_REPAIR_WATCH: ("WATCH", 0.00),
    BaseState.S5_RESTRENGTHEN: ("ALLOW_REENTRY", 1.00),
}


class RsiExitStateMachine:
    def __init__(self, initial_state: BaseState = BaseState.S0_MAIN_TREND) -> None:
        self.state = initial_state
        self.previous_rsi: float | None = None
        self.consecutive_below_60 = 0

    def step(
        self,
        *,
        rsi: float,
        close: float,
        ma20: float,
        external_risk: int = 0,
        hard_exit: int = 0,
    ) -> StateTransition:
        previous_state = self.state
        if _missing(rsi):
            action, cap = STATE_ACTIONS[self.state]
            return StateTransition(previous_state, self.state, "RSI_UNAVAILABLE", action, cap)

        below_60 = rsi < 60.0
        self.consecutive_below_60 = self.consecutive_below_60 + 1 if below_60 else 0
        below_ma20 = not _missing(ma20) and close < ma20
        above_ma20 = not _missing(ma20) and close > ma20

        if hard_exit:
            state, trigger = BaseState.S3_EXIT, "HARD_EXIT"
        elif rsi < 50.0:
            state, trigger = BaseState.S3_EXIT, "RSI_BELOW_50"
        elif below_60 and below_ma20:
            state, trigger = BaseState.S3_EXIT, "RSI_BELOW_60_AND_CLOSE_BELOW_MA20"
        elif self.consecutive_below_60 >= 2:
            state, trigger = BaseState.S3_EXIT, "RSI_BELOW_60_TWO_DAYS"
        elif previous_state == BaseState.S3_EXIT:
            if rsi >= 70.0 and above_ma20:
                state, trigger = BaseState.S5_RESTRENGTHEN, "RSI_ABOVE_70_AND_CLOSE_ABOVE_MA20"
            elif 60.0 <= rsi < 70.0 and above_ma20:
                state, trigger = BaseState.S4_REPAIR_WATCH, "RSI_REPAIRED_60_AND_CLOSE_ABOVE_MA20"
            else:
                state, trigger = BaseState.S3_EXIT, "EXIT_CONDITION_NOT_REPAIRED"
        elif previous_state in {BaseState.S4_REPAIR_WATCH, BaseState.S5_RESTRENGTHEN}:
            if rsi >= 70.0 and above_ma20:
                state, trigger = BaseState.S5_RESTRENGTHEN, "RESTRENGTHENED_ABOVE_70"
            elif 60.0 <= rsi < 70.0 and above_ma20:
                state, trigger = BaseState.S4_REPAIR_WATCH, "REPAIR_WATCH_CONTINUES"
            else:
                state, trigger = BaseState.S3_EXIT, "REPAIR_FAILED"
        elif rsi < 70.0 and below_ma20 and external_risk:
            state, trigger = BaseState.S2_RISK_DOWNGRADE, "MA20_BREAK_WITH_EXTERNAL_RISK"
        elif below_60:
            crossed = self.previous_rsi is None or self.previous_rsi >= 60.0
            state = BaseState.S2_RISK_DOWNGRADE
            trigger = "RSI_FIRST_BREAK_BELOW_60" if crossed else "RSI_REMAINS_BELOW_60"
        elif rsi >= 70.0:
            state, trigger = BaseState.S0_MAIN_TREND, "RSI_AT_OR_ABOVE_70"
        else:
            state, trigger = BaseState.S1_STRONG_PULLBACK, "RSI_60_TO_70"

        self.state = state
        self.previous_rsi = float(rsi)
        action, cap = STATE_ACTIONS[state]
        return StateTransition(previous_state, state, trigger, action, cap)

    def force_exit(self, trigger: str) -> StateTransition:
        previous = self.state
        self.state = BaseState.S3_EXIT
        action, cap = STATE_ACTIONS[self.state]
        return StateTransition(previous, self.state, trigger, action, cap)


def _missing(value: float) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))

