"""Pure flow-temperature functions (spec v0.1 §3.2, §3.3).

Heating curve, demand correction, return ceiling, cycling guard, DHW target and
hysteresis/min-hold. Nothing here knows about entities or Home Assistant; the
hub supplies filtered demand, toggle counts and sensor freshness, and the
coordinator calls these functions once per cycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .model import (
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


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# 1. Heating curve (§3.2.1)
# ---------------------------------------------------------------------------


def heating_curve(t_out: float, params: CurveParams = CurveParams()) -> float:
    """Weather-compensation curve, clamped to [flow_min, flow_max]."""
    span_out = params.room_design - params.design_outdoor
    if span_out <= 0:
        raise ValueError("room_design must be above design_outdoor")
    ratio = (params.room_design - t_out) / span_out
    if ratio <= 0:
        flow = params.room_design
    else:
        flow = params.room_design + (params.design_flow - params.room_design) * ratio ** (1.0 / params.n)
    return clamp(flow, params.flow_min, params.flow_max)


# ---------------------------------------------------------------------------
# 2. Demand correction (§3.2.2)
# ---------------------------------------------------------------------------


def demand_correction_step(
    state: DemandCorrectionState,
    demand_filtered: float | None,
    now: datetime,
    params: DemandCorrectionParams = DemandCorrectionParams(),
    active: bool = True,
) -> DemandCorrectionState:
    """Advance the demand-correction state machine by one cycle.

    Above `high_threshold` for `sustain_minutes` -> +step_k every step_period_minutes,
    up to +max_k. Below `low_threshold` for `sustain_minutes` -> mirrors down to -max_k.
    Between the thresholds the correction decays back towards 0 at the same cadence.

    `active=False` (v0.2.1 review fix 11 — idle/dhw) skips the high/low
    accumulation entirely and only decays any existing correction towards 0 at
    the normal cadence, so idle/dhw cannot accumulate the demand correction
    that heating built up (it would otherwise saturate at -8 while idle and
    heating would start 8 K low next time).
    """
    if demand_filtered is None:
        return state  # no data: hold the last correction

    if not active:
        if state.correction == 0.0:
            return state
        if state.last_step_at is not None and now - state.last_step_at < timedelta(minutes=params.step_period_minutes):
            return state
        if state.correction > 0:
            correction = max(0.0, state.correction - params.step_k)
        else:
            correction = min(0.0, state.correction + params.step_k)
        return DemandCorrectionState(correction=correction, high_since=None, low_since=None, last_step_at=now)

    high = demand_filtered > params.high_threshold
    low = demand_filtered < params.low_threshold

    high_since = now if high and state.high_since is None else (state.high_since if high else None)
    low_since = now if low and state.low_since is None else (state.low_since if low else None)

    def _step_due() -> bool:
        return state.last_step_at is None or now - state.last_step_at >= timedelta(minutes=params.step_period_minutes)

    correction = state.correction
    stepped = False
    if high and high_since is not None and now - high_since >= timedelta(minutes=params.sustain_minutes):
        if _step_due():
            correction = min(params.max_k, correction + params.step_k)
            stepped = True
    elif low and low_since is not None and now - low_since >= timedelta(minutes=params.sustain_minutes):
        if _step_due():
            correction = max(-params.max_k, correction - params.step_k)
            stepped = True
    elif not high and not low and correction != 0.0:
        if _step_due():
            if correction > 0:
                correction = max(0.0, correction - params.step_k)
            else:
                correction = min(0.0, correction + params.step_k)
            stepped = True

    return DemandCorrectionState(
        correction=correction,
        high_since=high_since,
        low_since=low_since,
        last_step_at=now if stepped else state.last_step_at,
    )


# ---------------------------------------------------------------------------
# 3. Return ceiling — heating (§3.2.3)
# ---------------------------------------------------------------------------


def return_ceiling_step(
    state: ReturnCorrectionState,
    return_temp: float | None,
    fresh: bool,
    params: ReturnCeilingParams = ReturnCeilingParams(),
) -> ReturnCorrectionState:
    """Return-ceiling correction. Acts every cycle (no min_hold gate); only
    when the return sensor is available and fresh (< freshness_minutes)."""
    if return_temp is None or not fresh:
        return state  # stale/missing: freeze the last correction
    if return_temp > params.return_ceiling:
        return ReturnCorrectionState(max(params.floor_k, state.correction - params.step_k))
    # below ceiling: recover towards 0 at the same rate
    return ReturnCorrectionState(min(0.0, state.correction + params.step_k))


# ---------------------------------------------------------------------------
# 4. Cycling guard — heating (§3.2.4). Flat penalty while the condition holds.
# ---------------------------------------------------------------------------


def cycling_guard_correction(
    toggle_count: int,
    demand_filtered: float | None,
    params: CyclingGuardParams = CyclingGuardParams(),
) -> float:
    if toggle_count < params.toggle_threshold:
        return 0.0
    if demand_filtered is not None and demand_filtered >= params.demand_threshold:
        return 0.0  # high demand + cycling: not a flow-temperature problem
    return -params.step_k


# ---------------------------------------------------------------------------
# 5. Floor (§3.2.5) — phase 1 uses flow_min only
# ---------------------------------------------------------------------------


def heating_target(
    t_out: float,
    demand_state: DemandCorrectionState,
    return_state: ReturnCorrectionState,
    cycling_correction: float,
    params: CurveParams = CurveParams(),
) -> float:
    """Combine curve + corrections, clamped to [flow_min, flow_max] (floor = flow_min)."""
    curve = heating_curve(t_out, params)
    total = curve + demand_state.correction + return_state.correction + cycling_correction
    return clamp(total, params.flow_min, params.flow_max)


# ---------------------------------------------------------------------------
# 6. DHW target (§3.3)
# ---------------------------------------------------------------------------


def dhw_return_correction(return_temp: float | None, fresh: bool, params: DhwParams = DhwParams()) -> float:
    if return_temp is None or not fresh:
        return 0.0
    return -params.return_step_k if return_temp > params.dhw_return_ceiling else 0.0


def dhw_cycling_correction(
    state: DhwCyclingState,
    toggle_count: int,
    now: datetime,
    params: DhwParams = DhwParams(),
) -> tuple[float, DhwCyclingState, bool]:
    """Returns (correction, new_state, issue_raised).

    `toggle_count` is the ignition count in the trailing window that occurred
    *after* `state.last_intervention_at` (v0.2.1 review fix 3a), not the raw
    window total: otherwise the same batch of ignitions sitting in the
    10-minute window would keep re-triggering an attempt on every 60 s poll,
    reaching the sticky hold in 2 minutes instead of across genuinely separate
    episodes. First cycling episode: -cycling_step_k and log. If cycling
    persists into a second episode, hold at dhw_flow_min and raise a repair
    issue (§3.3.3); the hold is sticky until cleared outside this function
    (the coil/pump/min-power need attention, software cannot fix it).
    """
    if state.holding:
        return 0.0, state, False  # already holding; caller clamps to dhw_flow_min
    cycling = toggle_count >= params.toggle_threshold
    if not cycling:
        # Quiet poll: an episode is still in flight — keep the correction and
        # the attempt count. Dropping them here would pop the flow back up
        # after 60 s and make the fail limit unreachable while the boiler is
        # still accumulating post-intervention ignitions. Attempts reset at
        # charge end (coordinator), not on a quiet poll.
        return state.correction_k, state, False
    attempts = state.attempts + 1
    if attempts >= params.cycling_fail_limit:
        return 0.0, DhwCyclingState(attempts=attempts, holding=True, last_intervention_at=now, correction_k=state.correction_k), True
    correction = state.correction_k - params.cycling_step_k
    return correction, DhwCyclingState(attempts=attempts, holding=False, last_intervention_at=now, correction_k=correction), False


def dhw_target(
    cylinder_temp: float,
    return_temp: float | None,
    return_fresh: bool,
    toggle_count: int,
    cycling_state: DhwCyclingState,
    now: datetime,
    params: DhwParams = DhwParams(),
) -> tuple[float, DhwCyclingState, bool]:
    """Returns (target flow, new cycling state, issue_raised).

    v0.2.1 review fix 4: the base (cylinder + delta) is clamped to
    [dhw_flow_min, dhw_flow_max] *before* corrections are applied, then only
    floored at dhw_flow_min afterwards — otherwise a -3/-5 K correction at the
    70 °C ceiling was clamped straight back up to 70 and silently disappeared.
    """
    cycling_correction, new_state, issue_raised = dhw_cycling_correction(cycling_state, toggle_count, now, params)
    if new_state.holding:
        return params.dhw_flow_min, new_state, issue_raised
    base = clamp(cylinder_temp + params.dhw_delta, params.dhw_flow_min, params.dhw_flow_max)
    return_correction = dhw_return_correction(return_temp, return_fresh, params)
    total = base + return_correction + cycling_correction
    return max(params.dhw_flow_min, total), new_state, issue_raised


# ---------------------------------------------------------------------------
# Hysteresis and hold (§3.2.6)
# ---------------------------------------------------------------------------


def should_write(
    new_value: float,
    memory: WriteMemory,
    now: datetime,
    params: HysteresisParams = HysteresisParams(),
    exempt: bool = False,
) -> bool:
    """True when the value differs enough and enough time has passed, or `exempt`
    (the return ceiling, and leaving DHW mode, may act every cycle).

    v0.2.1 review fix 1: the min-hold is gated on `last_target_change`, not
    `last_written_at` — the latter advances on every re-assertion (change 2),
    so under re-assertion it never stops being "recent" and a target change
    >= hysteresis_k would be blocked forever. Falls back to `last_written_at`
    when `last_target_change` is None (e.g. state persisted before this fix).
    """
    if exempt:
        return True
    if memory.last_written_setpoint is None:
        return True
    if abs(new_value - memory.last_written_setpoint) < params.hysteresis_k:
        return False
    last_change = memory.last_target_change if memory.last_target_change is not None else memory.last_written_at
    if last_change is not None and now - last_change < timedelta(minutes=params.min_hold_minutes):
        return False
    return True
