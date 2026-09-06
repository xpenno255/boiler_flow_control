"""Mode decision table, manual-hold detection, and the write-or-not decision
(spec v0.1 §3.1, §3.2.6, §4).

Pure functions over plain inputs. The coordinator gathers the inputs from Home
Assistant, calls `decide_mode` then `decide_write`, and performs at most one
`number.set_value` call.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .model import HysteresisParams, ManualHoldParams, ManualHoldState, Mode, WriteMemory
from .curve import should_write


class Action(str, Enum):
    NONE = "none"
    WRITE = "write"


class Override(str, Enum):
    AUTO = "auto"
    SHADOW = "shadow"
    HOLD = "hold"


@dataclass(frozen=True)
class ModeInputs:
    enabled: bool
    heat_demand: bool
    dhw_demand: bool
    manual_hold_active: bool


@dataclass(frozen=True)
class Decision:
    mode: Mode
    action: Action
    setpoint: float | None  # value to write when action is WRITE
    reason: str
    would_write: float | None  # what would be written if override were "auto"
    memory: WriteMemory  # updated memory for the coordinator to persist


# ---------------------------------------------------------------------------
# Manual hold detection (§3.1 manual_hold row)
# ---------------------------------------------------------------------------


def detect_manual_hold(
    current_value: float | None,
    last_written: float | None,
    now: datetime,
    state: ManualHoldState,
    params: ManualHoldParams = ManualHoldParams(),
) -> tuple[bool, ManualHoldState]:
    """True while the live setpoint differs from what we last wrote, for up to
    `hold_minutes`. Without a live reading or a prior write we cannot tell."""
    if current_value is None or last_written is None:
        return False, ManualHoldState(None)
    if abs(current_value - last_written) <= params.tolerance:
        return False, ManualHoldState(None)
    since = state.detected_at or now
    if now - since < timedelta(minutes=params.hold_minutes):
        return True, ManualHoldState(since)
    return False, ManualHoldState(None)  # hold expired: resume


# ---------------------------------------------------------------------------
# Mode decision table (§3.1)
# ---------------------------------------------------------------------------


def decide_mode(inputs: ModeInputs) -> Mode:
    if not inputs.enabled:
        return Mode.OFF
    if inputs.manual_hold_active:
        return Mode.MANUAL_HOLD
    if inputs.dhw_demand and inputs.heat_demand:
        return Mode.DHW_AND_HEATING
    if inputs.dhw_demand:
        return Mode.DHW
    if inputs.heat_demand:
        return Mode.HEATING
    return Mode.IDLE


# ---------------------------------------------------------------------------
# Write-or-not decision (§3.2.6, §4)
# ---------------------------------------------------------------------------


def decide_write(
    mode: Mode,
    target: float | None,
    override: Override,
    memory: WriteMemory,
    now: datetime,
    exempt_hysteresis: bool = False,
    hysteresis_params: HysteresisParams = HysteresisParams(),
) -> Decision:
    """One policy evaluation for the current cycle. `exempt_hysteresis` is set by
    the coordinator for the return-ceiling case and for leaving DHW mode (§3.3.4),
    both of which may act every cycle."""
    if mode is Mode.OFF:
        return Decision(mode, Action.NONE, None, "integration disabled", None, memory)
    if target is None:
        return Decision(mode, Action.NONE, None, "no target computed", None, memory)
    if mode is Mode.MANUAL_HOLD:
        return Decision(mode, Action.NONE, None, "manual hold: selflowtemp set by hand", target, memory)

    would_write = target
    if override is Override.HOLD:
        return Decision(mode, Action.NONE, None, "override: hold", would_write, memory)

    write_needed = should_write(target, memory, now, hysteresis_params, exempt=exempt_hysteresis)
    if not write_needed:
        return Decision(mode, Action.NONE, None, "unchanged; within hysteresis/min_hold", would_write, memory)

    if override is Override.SHADOW:
        return Decision(mode, Action.NONE, None, "shadow mode", would_write, memory)

    new_memory = WriteMemory(last_written_setpoint=target, last_written_at=now)
    return Decision(mode, Action.WRITE, target, f"mode={mode.value}", would_write, new_memory)
