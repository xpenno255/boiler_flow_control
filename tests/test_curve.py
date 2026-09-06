"""Tests for core.curve: heating curve, corrections, DHW target, hysteresis (spec §3.2, §3.3)."""
from datetime import datetime, timedelta, timezone

import pytest

from core.curve import (
    clamp,
    cycling_guard_correction,
    demand_correction_step,
    dhw_cycling_correction,
    dhw_return_correction,
    dhw_target,
    heating_curve,
    heating_target,
    return_ceiling_step,
    should_write,
)
from core.model import (
    CurveParams,
    CyclingGuardParams,
    DemandCorrectionParams,
    DemandCorrectionState,
    DhwCyclingState,
    DhwParams,
    HysteresisParams,
    ReturnCeilingParams,
    ReturnCorrectionState,
    WriteMemory,
)

T0 = datetime(2026, 1, 15, 7, 0, tzinfo=timezone.utc)


# --- heating curve (§3.2.1) --------------------------------------------------


def test_curve_at_design_outdoor_equals_design_flow():
    assert heating_curve(-3.0) == pytest.approx(55.0)


def test_curve_at_room_design_clamps_to_flow_min():
    # T_flow would equal room_design (20 °C), well below flow_min.
    assert heating_curve(20.0) == pytest.approx(35.0)


def test_curve_mild_weather_between_bounds():
    value = heating_curve(10.0)
    assert 35.0 < value < 55.0
    assert value == pytest.approx(38.44, abs=0.1)


def test_curve_extreme_cold_clamps_to_flow_max():
    assert heating_curve(-30.0) == pytest.approx(65.0)


def test_curve_custom_params():
    p = CurveParams(design_flow=45.0, design_outdoor=-5.0, room_design=18.0, flow_min=20.0, flow_max=45.0)
    assert heating_curve(-5.0, p) == pytest.approx(45.0)


def test_curve_rejects_bad_params():
    with pytest.raises(ValueError):
        heating_curve(0.0, CurveParams(room_design=-3.0, design_outdoor=-3.0))


# --- demand correction (§3.2.2) ---------------------------------------------


def _run_high(state, minutes_list, demand=80.0, params=DemandCorrectionParams()):
    now = T0
    for m in minutes_list:
        now = now + timedelta(minutes=m)
        state = demand_correction_step(state, demand, now, params)
    return state, now


def test_demand_none_holds_last_correction():
    s = DemandCorrectionState(correction=4.0)
    s2 = demand_correction_step(s, None, T0)
    assert s2 == s


def test_demand_high_no_step_before_sustained():
    s = DemandCorrectionState()
    s = demand_correction_step(s, 80.0, T0)
    s = demand_correction_step(s, 80.0, T0 + timedelta(minutes=5))
    assert s.correction == 0.0
    assert s.high_since == T0


def test_demand_high_steps_after_sustain_then_caps():
    s = DemandCorrectionState()
    now = T0
    # cross above threshold
    s = demand_correction_step(s, 80.0, now)
    # advance in 10-minute steps; correction should climb +2 each step once sustained,
    # capping at +8 after 4 steps (40 minutes sustained).
    seen = []
    for _ in range(8):
        now = now + timedelta(minutes=10)
        s = demand_correction_step(s, 80.0, now)
        seen.append(s.correction)
    assert seen[0] == 0.0  # 10 min: not yet sustained 20 min
    assert seen[1] == pytest.approx(2.0)  # 20 min sustained: first step
    assert seen[2] == pytest.approx(4.0)
    assert seen[3] == pytest.approx(6.0)
    assert seen[4] == pytest.approx(8.0)
    assert seen[5] == pytest.approx(8.0)  # capped
    assert seen[7] == pytest.approx(8.0)


def test_demand_low_steps_down_then_caps():
    s = DemandCorrectionState()
    now = T0
    s = demand_correction_step(s, 10.0, now)
    seen = []
    for _ in range(6):
        now = now + timedelta(minutes=10)
        s = demand_correction_step(s, 10.0, now)
        seen.append(s.correction)
    assert seen[1] == pytest.approx(-2.0)
    assert seen[4] == pytest.approx(-8.0)
    assert seen[5] == pytest.approx(-8.0)


def test_demand_between_thresholds_decays_towards_zero():
    s = DemandCorrectionState(correction=6.0)
    now = T0
    s = demand_correction_step(s, 50.0, now)  # between 30 and 70: no sustain needed to decay
    assert s.correction == pytest.approx(4.0)
    now = now + timedelta(minutes=10)
    s = demand_correction_step(s, 50.0, now)
    assert s.correction == pytest.approx(2.0)
    now = now + timedelta(minutes=10)
    s = demand_correction_step(s, 50.0, now)
    assert s.correction == pytest.approx(0.0)


def test_demand_step_gated_by_step_period():
    s = DemandCorrectionState()
    now = T0
    s = demand_correction_step(s, 80.0, now)
    now = now + timedelta(minutes=20)
    s = demand_correction_step(s, 80.0, now)
    assert s.correction == pytest.approx(2.0)
    now = now + timedelta(minutes=5)  # step period not elapsed yet
    s = demand_correction_step(s, 80.0, now)
    assert s.correction == pytest.approx(2.0)


# --- return ceiling, heating (§3.2.3) ---------------------------------------


def test_return_ceiling_unavailable_or_stale_freezes():
    s = ReturnCorrectionState(correction=-4.0)
    assert return_ceiling_step(s, None, True) == s
    assert return_ceiling_step(s, 55.0, False) == s


def test_return_ceiling_acts_every_cycle_no_gate():
    s = ReturnCorrectionState()
    s = return_ceiling_step(s, 55.0, True)
    assert s.correction == pytest.approx(-2.0)
    s = return_ceiling_step(s, 55.0, True)
    assert s.correction == pytest.approx(-4.0)


def test_return_ceiling_recovers_once_below():
    s = ReturnCorrectionState(correction=-4.0)
    s = return_ceiling_step(s, 45.0, True)
    assert s.correction == pytest.approx(-2.0)
    s = return_ceiling_step(s, 45.0, True)
    assert s.correction == pytest.approx(0.0)
    s = return_ceiling_step(s, 45.0, True)
    assert s.correction == pytest.approx(0.0)  # does not overshoot above 0


def test_return_ceiling_respects_floor():
    p = ReturnCeilingParams(floor_k=-3.0, step_k=2.0)
    s = ReturnCorrectionState()
    for _ in range(5):
        s = return_ceiling_step(s, 60.0, True, p)
    assert s.correction == pytest.approx(-3.0)


# --- cycling guard, heating (§3.2.4) -----------------------------------------


def test_cycling_guard_below_threshold_is_zero():
    assert cycling_guard_correction(2, 20.0) == 0.0


def test_cycling_guard_high_demand_does_nothing():
    assert cycling_guard_correction(4, 80.0) == 0.0


def test_cycling_guard_low_demand_applies_penalty():
    assert cycling_guard_correction(4, 20.0) == pytest.approx(-3.0)


def test_cycling_guard_no_demand_data_applies_penalty():
    assert cycling_guard_correction(4, None) == pytest.approx(-3.0)


# --- heating_target composition ----------------------------------------------


def test_heating_target_combines_and_clamps():
    demand = DemandCorrectionState(correction=8.0)
    ret = ReturnCorrectionState(correction=-2.0)
    value = heating_target(-3.0, demand, ret, -3.0)
    # curve(-3)=55; 55+8-2-3=58, within [35,65]
    assert value == pytest.approx(58.0)


def test_heating_target_never_below_flow_min():
    demand = DemandCorrectionState(correction=-8.0)
    ret = ReturnCorrectionState(correction=-8.0)
    value = heating_target(20.0, demand, ret, -3.0)  # curve clamps to 35 already
    assert value == pytest.approx(35.0)


# --- DHW target (§3.3) -------------------------------------------------------


def test_dhw_target_basic_clamped():
    value, state, issue = dhw_target(30.0, None, False, 0, DhwCyclingState())
    assert value == pytest.approx(55.0)  # 30+20=50, clamped to dhw_flow_min 55
    assert not issue and not state.holding

    value2, _, _ = dhw_target(55.0, None, False, 0, DhwCyclingState())
    assert value2 == pytest.approx(70.0)  # 55+20=75, clamped to dhw_flow_max 70

    value3, _, _ = dhw_target(45.0, None, False, 0, DhwCyclingState())
    assert value3 == pytest.approx(65.0)  # 45+20=65, within bounds


def test_dhw_return_correction_only_when_fresh_and_over_ceiling():
    assert dhw_return_correction(65.0, True) == pytest.approx(-3.0)
    assert dhw_return_correction(55.0, True) == 0.0
    assert dhw_return_correction(65.0, False) == 0.0
    assert dhw_return_correction(None, True) == 0.0


def test_dhw_cycling_first_episode_then_second_holds_and_raises_issue():
    state = DhwCyclingState()
    correction, state, issue = dhw_cycling_correction(state, 4)
    assert correction == pytest.approx(-5.0) and not issue and not state.holding
    correction, state, issue = dhw_cycling_correction(state, 4)
    assert issue and state.holding and correction == 0.0
    # sticky: still holding even if cycling has stopped
    correction, state, issue = dhw_cycling_correction(state, 0)
    assert state.holding and not issue


def test_dhw_cycling_clears_attempts_when_not_cycling():
    state = DhwCyclingState(attempts=1)
    correction, state, issue = dhw_cycling_correction(state, 0)
    assert correction == 0.0 and state.attempts == 0 and not state.holding and not issue


def test_dhw_target_holds_at_floor_after_second_cycling_failure():
    state = DhwCyclingState()
    _, state, _ = dhw_target(40.0, None, False, 5, state)
    value, state, issue = dhw_target(40.0, None, False, 5, state)
    assert issue and value == pytest.approx(55.0) and state.holding


# --- hysteresis / min-hold (§3.2.6) ------------------------------------------


def test_should_write_first_time_true():
    assert should_write(50.0, WriteMemory(), T0)


def test_should_write_small_change_false():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    assert not should_write(50.5, m, T0 + timedelta(minutes=30))


def test_should_write_big_change_within_min_hold_false():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    assert not should_write(52.0, m, T0 + timedelta(minutes=5))


def test_should_write_big_change_past_min_hold_true():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    assert should_write(52.0, m, T0 + timedelta(minutes=11))


def test_should_write_exempt_bypasses_everything():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    assert should_write(50.2, m, T0 + timedelta(seconds=1), exempt=True)


def test_clamp_helper():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
