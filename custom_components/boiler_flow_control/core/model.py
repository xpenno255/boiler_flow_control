"""Shared dataclasses, enums and parameter defaults for Boiler Flow Control (spec v0.1, §3).

Nothing here touches Home Assistant. `curve.py` operates on these types to produce
a flow-temperature target; `policy.py` decides the mode and whether to write it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Mode(str, Enum):
    """§3.1 mode table."""

    IDLE = "idle"
    HEATING = "heating"
    DHW = "dhw"
    DHW_AND_HEATING = "dhw_and_heating"
    MANUAL_HOLD = "manual_hold"
    OFF = "off"


# ---------------------------------------------------------------------------
# Heating curve (§3.2.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurveParams:
    design_flow: float = 55.0
    design_outdoor: float = -3.0
    room_design: float = 20.0
    n: float = 1.3
    flow_min: float = 35.0
    flow_max: float = 65.0


# ---------------------------------------------------------------------------
# Demand correction (§3.2.2) — a cumulative correction that steps over time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DemandCorrectionParams:
    high_threshold: float = 70.0
    low_threshold: float = 30.0
    sustain_minutes: float = 20.0
    step_k: float = 2.0
    step_period_minutes: float = 10.0
    max_k: float = 8.0


@dataclass(frozen=True)
class DemandCorrectionState:
    correction: float = 0.0
    high_since: datetime | None = None
    low_since: datetime | None = None
    last_step_at: datetime | None = None


# ---------------------------------------------------------------------------
# Return ceiling (§3.2.3) — heating side; acts every cycle, no min_hold gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnCeilingParams:
    return_ceiling: float = 50.0
    step_k: float = 2.0
    freshness_minutes: float = 10.0
    floor_k: float = -20.0  # safety bound: how far this correction may push down


@dataclass(frozen=True)
class ReturnCorrectionState:
    correction: float = 0.0


# ---------------------------------------------------------------------------
# Cycling guard (§3.2.4) — heating side; flat penalty while condition holds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CyclingGuardParams:
    toggle_threshold: int = 3
    window_minutes: float = 10.0
    demand_threshold: float = 50.0
    step_k: float = 3.0


# ---------------------------------------------------------------------------
# DHW (§3.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DhwParams:
    dhw_delta: float = 20.0
    dhw_flow_min: float = 55.0
    dhw_flow_max: float = 70.0
    dhw_return_ceiling: float = 60.0
    return_step_k: float = 3.0
    cycling_step_k: float = 5.0
    cycling_fail_limit: int = 2
    toggle_threshold: int = 3
    window_minutes: float = 10.0


@dataclass(frozen=True)
class DhwCyclingState:
    """Tracks whether the cycling guard has already tried once and failed."""

    attempts: int = 0
    holding: bool = False  # sticky: once True, stays True until manually cleared


# ---------------------------------------------------------------------------
# Hysteresis / min-hold (§3.2.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HysteresisParams:
    min_hold_minutes: float = 10.0
    hysteresis_k: float = 1.0


@dataclass(frozen=True)
class WriteMemory:
    """What we last wrote, persisted by the coordinator (survives restart)."""

    last_written_setpoint: float | None = None
    last_written_at: datetime | None = None


# ---------------------------------------------------------------------------
# Manual hold (§3.1 manual_hold row)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualHoldParams:
    hold_minutes: float = 30.0
    tolerance: float = 0.5


@dataclass(frozen=True)
class ManualHoldState:
    detected_at: datetime | None = None
