"""Tests for core.policy: mode table, manual hold, write-or-not decision (spec §3.1, §3.2.6)."""
from datetime import datetime, timedelta, timezone

import pytest

from core.model import HysteresisParams, ManualHoldParams, ManualHoldState, Mode, WriteMemory
from core.policy import Action, ModeInputs, Override, decide_mode, decide_write, detect_manual_hold

T0 = datetime(2026, 1, 15, 7, 0, tzinfo=timezone.utc)


# --- mode table (§3.1) -------------------------------------------------------


def test_mode_off_when_disabled():
    assert decide_mode(ModeInputs(enabled=False, heat_demand=True, dhw_demand=True, manual_hold_active=True)) is Mode.OFF


def test_mode_manual_hold_beats_demand():
    assert decide_mode(ModeInputs(enabled=True, heat_demand=True, dhw_demand=True, manual_hold_active=True)) is Mode.MANUAL_HOLD


def test_mode_idle_when_no_demand():
    assert decide_mode(ModeInputs(enabled=True, heat_demand=False, dhw_demand=False, manual_hold_active=False)) is Mode.IDLE


def test_mode_heating_only():
    assert decide_mode(ModeInputs(enabled=True, heat_demand=True, dhw_demand=False, manual_hold_active=False)) is Mode.HEATING


def test_mode_dhw_only():
    assert decide_mode(ModeInputs(enabled=True, heat_demand=False, dhw_demand=True, manual_hold_active=False)) is Mode.DHW


def test_mode_dhw_and_heating():
    assert decide_mode(ModeInputs(enabled=True, heat_demand=True, dhw_demand=True, manual_hold_active=False)) is Mode.DHW_AND_HEATING


# --- manual hold detection ----------------------------------------------------


def test_manual_hold_no_data_is_false():
    active, state = detect_manual_hold(None, 50.0, T0, ManualHoldState())
    assert not active and state.detected_at is None
    active, state = detect_manual_hold(55.0, None, T0, ManualHoldState())
    assert not active


def test_manual_hold_within_tolerance_is_false():
    active, state = detect_manual_hold(50.2, 50.0, T0, ManualHoldState())
    assert not active


def test_manual_hold_detected_then_holds_then_expires():
    active, state = detect_manual_hold(60.0, 50.0, T0, ManualHoldState())
    assert active and state.detected_at == T0
    # 20 minutes later, still within the 30-minute default hold
    active, state = detect_manual_hold(60.0, 50.0, T0 + timedelta(minutes=20), state)
    assert active and state.detected_at == T0
    # 31 minutes later: hold has expired, resume
    active, state = detect_manual_hold(60.0, 50.0, T0 + timedelta(minutes=31), state)
    assert not active and state.detected_at is None


def test_manual_hold_custom_params():
    p = ManualHoldParams(hold_minutes=5.0, tolerance=1.0)
    active, state = detect_manual_hold(50.5, 50.0, T0, ManualHoldState(), p)
    assert not active  # within the wider tolerance
    active, state = detect_manual_hold(55.0, 50.0, T0, ManualHoldState(), p)
    assert active
    active, state = detect_manual_hold(55.0, 50.0, T0 + timedelta(minutes=6), state, p)
    assert not active


# --- write-or-not decision (§3.2.6, §4) --------------------------------------


def test_decide_write_off_never_writes():
    d = decide_write(Mode.OFF, 50.0, Override.AUTO, WriteMemory(), T0)
    assert d.action is Action.NONE and d.would_write is None


def test_decide_write_no_target_reports_none():
    d = decide_write(Mode.HEATING, None, Override.AUTO, WriteMemory(), T0)
    assert d.action is Action.NONE and d.would_write is None


def test_decide_write_manual_hold_reports_would_write_but_no_action():
    d = decide_write(Mode.MANUAL_HOLD, 50.0, Override.AUTO, WriteMemory(), T0)
    assert d.action is Action.NONE and d.would_write == 50.0


def test_decide_write_override_hold_never_writes():
    d = decide_write(Mode.HEATING, 50.0, Override.HOLD, WriteMemory(), T0)
    assert d.action is Action.NONE and d.would_write == 50.0


def test_decide_write_first_cycle_writes_in_auto():
    d = decide_write(Mode.HEATING, 50.0, Override.AUTO, WriteMemory(), T0)
    assert d.action is Action.WRITE and d.setpoint == 50.0
    assert d.memory.last_written_setpoint == 50.0 and d.memory.last_written_at == T0


def test_decide_write_shadow_never_writes_but_reports_would_write():
    d = decide_write(Mode.HEATING, 50.0, Override.SHADOW, WriteMemory(), T0)
    assert d.action is Action.NONE and d.would_write == 50.0
    assert d.memory.last_written_setpoint is None  # shadow does not persist a write


def test_decide_write_unchanged_within_hysteresis_does_not_write():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    d = decide_write(Mode.HEATING, 50.4, Override.AUTO, m, T0 + timedelta(minutes=30))
    assert d.action is Action.NONE


def test_decide_write_big_change_within_min_hold_waits():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    d = decide_write(Mode.HEATING, 53.0, Override.AUTO, m, T0 + timedelta(minutes=2))
    assert d.action is Action.NONE


def test_decide_write_exempt_bypasses_min_hold():
    m = WriteMemory(last_written_setpoint=50.0, last_written_at=T0)
    d = decide_write(Mode.HEATING, 53.0, Override.AUTO, m, T0 + timedelta(minutes=2), exempt_hysteresis=True)
    assert d.action is Action.WRITE and d.setpoint == 53.0
