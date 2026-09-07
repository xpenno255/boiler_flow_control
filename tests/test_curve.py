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


def test_demand_inactive_decays_towards_zero_even_with_high_demand():
    # v0.2.1 review fix 11: idle/dhw must not accumulate the demand correction;
    # a saturated +8 must decay back towards 0 even while demand reads high.
    s = DemandCorrectionState(correction=8.0)
    now = T0
    s = demand_correction_step(s, 90.0, now, active=False)
    assert s.correction == pytest.approx(6.0)
    now = now + timedelta(minutes=10)
    s = demand_correction_step(s, 90.0, now, active=False)
    assert s.correction == pytest.approx(4.0)


def test_demand_inactive_holds_at_zero():
    s = DemandCorrectionState(correction=0.0)
    s2 = demand_correction_step(s, 90.0, T0, active=False)
    assert s2 == s


def test_demand_inactive_negative_decays_upward():
    s = DemandCorrectionState(correction=-8.0)
    s = demand_correction_step(s, 5.0, T0, active=False)
    assert s.correction == pytest.approx(-6.0)


def test_demand_none_still_freezes_regardless_of_active():
    s = DemandCorrectionState(correction=4.0)
    assert demand_correction_step(s, None, T0, active=False) == s


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
    value, state, issue = dhw_target(30.0, None, False, 0, DhwCyclingState(), T0)
    assert value == pytest.approx(55.0)  # 30+20=50, clamped to dhw_flow_min 55
    assert not issue and not state.holding

    value2, _, _ = dhw_target(55.0, None, False, 0, DhwCyclingState(), T0)
    assert value2 == pytest.approx(70.0)  # 55+20=75, clamped to dhw_flow_max 70

    value3, _, _ = dhw_target(45.0, None, False, 0, DhwCyclingState(), T0)
    assert value3 == pytest.approx(65.0)  # 45+20=65, within bounds


def test_dhw_target_correction_applied_after_clamp_not_before():
    # v0.2.1 review fix 4: at the dhw_flow_max ceiling, a return-ceiling
    # correction must actually reduce the target, not vanish because the
    # pre-correction sum was reclamped back up to the ceiling.
    value, _, _ = dhw_target(55.0, 65.0, True, 0, DhwCyclingState(), T0)
    # base = clamp(55+20, 55, 70) = 70; return correction -3 => 67, not 70.
    assert value == pytest.approx(67.0)


def test_dhw_return_correction_only_when_fresh_and_over_ceiling():
    assert dhw_return_correction(65.0, True) == pytest.approx(-3.0)
    assert dhw_return_correction(55.0, True) == 0.0
    assert dhw_return_correction(65.0, False) == 0.0
    assert dhw_return_correction(None, True) == 0.0


def test_dhw_cycling_first_episode_then_second_holds_and_raises_issue():
    state = DhwCyclingState()
    correction, state, issue = dhw_cycling_correction(state, 4, T0)
    assert correction == pytest.approx(-5.0) and not issue and not state.holding
    assert state.last_intervention_at == T0
    correction, state, issue = dhw_cycling_correction(state, 4, T0 + timedelta(minutes=15))
    assert issue and state.holding and correction == 0.0
    # sticky: still holding even if cycling has stopped
    correction, state, issue = dhw_cycling_correction(state, 0, T0 + timedelta(minutes=30))
    assert state.holding and not issue


def test_dhw_cycling_quiet_poll_preserves_attempts_and_correction():
    # A quiet poll mid-episode must not drop the intervention: the -5 K keeps
    # holding the flow down and the attempt stays counted while we wait to see
    # whether new ignitions accrue. Reset happens at charge end (coordinator).
    state = DhwCyclingState(attempts=1, last_intervention_at=T0, correction_k=-5.0)
    correction, state, issue = dhw_cycling_correction(state, 0, T0 + timedelta(seconds=60))
    assert correction == pytest.approx(-5.0) and state.attempts == 1 and not state.holding and not issue


def test_dhw_target_holds_at_floor_after_second_cycling_failure():
    state = DhwCyclingState()
    _, state, _ = dhw_target(40.0, None, False, 5, state, T0)
    value, state, issue = dhw_target(40.0, None, False, 5, state, T0 + timedelta(minutes=15))
    assert issue and value == pytest.approx(55.0) and state.holding


# --- DHW cycling episode semantics (v0.2.1 review fix 3a) --------------------


def test_dhw_cycling_only_ignitions_after_intervention_count():
    # Simulates the coordinator passing ignitions-since-last-intervention:
    # the same stale count sitting in the window (as `cycles_10min` would
    # report every poll) must not keep re-triggering attempts.
    state = DhwCyclingState()
    correction, state, issue = dhw_cycling_correction(state, 4, T0)
    assert correction == pytest.approx(-5.0) and not state.holding
    # 60s later: coordinator recomputes ignitions-since-intervention, which is
    # 0 (no new ignitions since T0) even though the raw window count is still 4.
    # No new attempt fires, and the standing -5 K correction persists.
    correction, state, issue = dhw_cycling_correction(state, 0, T0 + timedelta(seconds=60))
    assert correction == pytest.approx(-5.0) and state.attempts == 1 and not issue
    # Once genuinely new ignitions accumulate past the threshold, the first
    # intervention has failed: second attempt hits the fail limit and holds.
    correction, state, issue = dhw_cycling_correction(state, 3, T0 + timedelta(minutes=8))
    assert state.holding and issue and correction == 0.0


def test_dhw_cycling_persisting_episode_reaches_sticky_hold():
    # Full arc: intervene at -5 K, quiet polls keep it applied, boiler keeps
    # cycling anyway -> new post-intervention ignitions -> sticky hold + issue.
    state = DhwCyclingState()
    correction, state, _ = dhw_cycling_correction(state, 3, T0)
    assert correction == pytest.approx(-5.0)
    for m in (1, 2, 3):  # quiet polls while new ignitions accrue below threshold
        correction, state, issue = dhw_cycling_correction(state, m - 1, T0 + timedelta(minutes=m))
        assert correction == pytest.approx(-5.0) and not state.holding and not issue
    correction, state, issue = dhw_cycling_correction(state, 3, T0 + timedelta(minutes=4))
    assert state.holding and issue


def test_dhw_target_shadow_computation_does_not_mutate_input_state():
    # dhw_target/dhw_cycling_correction are pure: calling them for a "would
    # write" preview must not affect the caller's own state object.
    state = DhwCyclingState(attempts=1)
    _value, new_state, _issue = dhw_target(40.0, None, False, 4, state, T0)
    assert state.attempts == 1  # original untouched
    assert new_state.attempts == 2


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


def test_should_write_gates_on_last_target_change_not_last_written_at():
    # v0.2.1 review fix 1: under re-assertion, last_written_at advances every
    # cycle (change 2) but last_target_change only advances when the target
    # itself changes. A big change must unblock once min_hold has elapsed
    # since last_target_change, even though last_written_at is only seconds old.
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0, last_target_change=T0)
    now = T0
    for _ in range(20):  # simulate 20 re-assertion cycles (60s poll), each bumping last_written_at
        now = now + timedelta(minutes=1)
        m = WriteMemory(last_written_setpoint=50.0, last_written_at=now, last_target_change=T0)
    # last_written_at is now ~20 min old (recent), last_target_change is still T0 (>10 min ago)
    assert should_write(53.0, m, now)


def test_should_write_falls_back_to_last_written_at_when_no_target_change_recorded():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0, last_target_change=None)
    assert not should_write(53.0, m, T0 + timedelta(minutes=2))
    assert should_write(53.0, m, T0 + timedelta(minutes=11))


def test_clamp_helper():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
