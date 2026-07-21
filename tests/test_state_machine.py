from __future__ import annotations

from rsi_exit.models import BaseState
from rsi_exit.position_rules import merge_position_caps
from rsi_exit.state_machine import RsiExitStateMachine


def step(machine: RsiExitStateMachine, rsi: float, close: float = 110, ma20: float = 100):
    return machine.step(rsi=rsi, close=close, ma20=ma20)


def test_s0_to_s1() -> None:
    machine = RsiExitStateMachine()
    assert step(machine, 75).current_state == BaseState.S0_MAIN_TREND
    assert step(machine, 65).current_state == BaseState.S1_STRONG_PULLBACK


def test_s1_to_s2_on_first_break_below_60() -> None:
    machine = RsiExitStateMachine()
    step(machine, 65)
    transition = step(machine, 59)
    assert transition.current_state == BaseState.S2_RISK_DOWNGRADE
    assert transition.position_cap == 0.5


def test_two_days_below_60_enters_s3() -> None:
    machine = RsiExitStateMachine()
    step(machine, 65)
    step(machine, 59)
    assert step(machine, 58).current_state == BaseState.S3_EXIT


def test_below_60_and_below_ma20_enters_s3_immediately() -> None:
    machine = RsiExitStateMachine()
    step(machine, 65)
    assert step(machine, 59, close=90, ma20=100).current_state == BaseState.S3_EXIT


def test_below_50_enters_s3() -> None:
    assert step(RsiExitStateMachine(), 49).current_state == BaseState.S3_EXIT


def test_s3_repairs_to_s4() -> None:
    machine = RsiExitStateMachine()
    step(machine, 49)
    assert step(machine, 65, close=110, ma20=100).current_state == BaseState.S4_REPAIR_WATCH


def test_s4_restrengthens_to_s5() -> None:
    machine = RsiExitStateMachine()
    step(machine, 49)
    step(machine, 65)
    transition = step(machine, 72)
    assert transition.current_state == BaseState.S5_RESTRENGTHEN
    assert transition.action == "ALLOW_REENTRY"


def test_external_risk_and_ma20_break_downgrades() -> None:
    machine = RsiExitStateMachine()
    transition = machine.step(rsi=65, close=90, ma20=100, external_risk=1)
    assert transition.current_state == BaseState.S2_RISK_DOWNGRADE


def test_final_cap_is_smaller_of_base_and_signal() -> None:
    action, cap = merge_position_caps(
        base_action="REDUCE", base_cap=0.5, signal_action="REDUCE_TO_70", signal_cap=0.7
    )
    assert action == "REDUCE"
    assert cap == 0.5

