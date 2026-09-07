"""HA glue: gather inputs, run the hub + core, and act once (spec v0.1 §3–§5).

All decisions live in `core.curve` and `core.policy`. This module reads
entities, converts units, calls the pure functions, performs at most one
`number.set_value` service call, and publishes a snapshot for the entities.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BURNER_POWER_ENTITY,
    CONF_CURRENT_FLOW_ENTITY,
    CONF_CYLINDER_TEMP_ENTITY,
    CONF_DESIGN_FLOW,
    CONF_DESIGN_OUTDOOR,
    CONF_DHW_DELTA,
    CONF_DHW_FLOW_MAX,
    CONF_DHW_FLOW_MIN,
    CONF_DHW_RETURN_CEILING,
    CONF_FLOW_MAX,
    CONF_FLOW_MIN,
    CONF_FLOW_SETPOINT_ENTITY,
    CONF_HEAT_DEMAND_ENTITY,
    CONF_HEATING_ACTIVE_ENTITY,
    CONF_HW_RELAY_DEMAND_ENTITY,
    CONF_MANUAL_HOLD_MINUTES,
    CONF_MAX_FLOW_ENTITY,
    CONF_MIN_HOLD_MINUTES,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_RETURN_CEILING,
    CONF_RETURN_TEMP_ENTITY,
    CONF_ZONE_DEMAND_ENTITIES,
    DEFAULT_DESIGN_FLOW,
    DEFAULT_DESIGN_OUTDOOR,
    DEFAULT_DHW_DELTA,
    DEFAULT_DHW_FLOW_MAX,
    DEFAULT_DHW_FLOW_MIN,
    DEFAULT_DHW_RETURN_CEILING,
    DEFAULT_FLOW_MAX,
    DEFAULT_FLOW_MIN,
    DEFAULT_MANUAL_HOLD_MINUTES,
    DEFAULT_MIN_HOLD_MINUTES,
    DEFAULT_OVERRIDE,
    DEFAULT_RETURN_CEILING,
    DOMAIN,
    ROOM_DESIGN_TEMP,
    UPDATE_INTERVAL_SECONDS,
)
from .core.curve import (
    cycling_guard_correction,
    demand_correction_step,
    dhw_target,
    heating_curve,
    heating_target,
    return_ceiling_step,
    should_write,
)
from .core.model import (
    CurveParams,
    CyclingGuardParams,
    DemandCorrectionParams,
    DemandCorrectionState,
    DhwParams,
    HysteresisParams,
    ManualHoldParams,
    ManualHoldState,
    Mode,
    ReturnCeilingParams,
    ReturnCorrectionState,
)
from .core.policy import (
    Action,
    Decision,
    ModeInputs,
    Override,
    decide_mode,
    decide_write,
    detect_manual_hold,
    infer_dhw_demand,
    zone_max_demand,
)
from .hub import BoilerFlowHub
from .store import BFCStore

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = ("unknown", "unavailable", "", None)


@dataclass
class BFCCoordinatorData:
    """Snapshot published to entities after each cycle."""

    mode: str = Mode.OFF.value
    reason: str = ""
    action: str = Action.NONE.value
    enabled: bool = True
    override: str = DEFAULT_OVERRIDE
    last_run: datetime | None = None
    last_write: datetime | None = None
    last_written_setpoint: float | None = None
    last_target_change: datetime | None = None
    no_boiler: bool = False
    # Target
    flow_setpoint: float | None = None  # value we did/would write
    would_write: float | None = None
    curve: float | None = None
    demand_correction: float = 0.0
    return_correction: float = 0.0
    cycling_correction: float = 0.0
    demand_filtered: float | None = None
    cycles_10min: int = 0
    return_temperature_used: float | None = None
    return_fresh: bool = False
    manual_hold_active: bool = False
    dhw_issue_raised: bool = False
    # Raw inputs
    outdoor_temp: float | None = None
    current_flow: float | None = None
    heat_demand: float | None = None
    aggregate_heat_demand: float | None = None
    zone_max_demand: float | None = None
    hw_relay_demand: float | None = None
    cylinder_temp: float | None = None
    max_flow: float | None = None
    live_setpoint: float | None = None
    # Diagnostics
    disabled_features: list[str] = field(default_factory=list)


class BFCCoordinator(DataUpdateCoordinator[BFCCoordinatorData]):
    """Single hub-style coordinator for Boiler Flow Control."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: BFCStore, hub: BoilerFlowHub) -> None:
        self._entry = entry
        self._store = store
        self._hub = hub
        self._config: dict[str, Any] = {**entry.data, **entry.options}
        self._enabled = True
        self._override = str(self._config.get("mode_override", DEFAULT_OVERRIDE))
        self._tunables: dict[str, float] = {
            CONF_DESIGN_FLOW: float(store.get(CONF_DESIGN_FLOW, DEFAULT_DESIGN_FLOW)),
            CONF_DESIGN_OUTDOOR: float(store.get(CONF_DESIGN_OUTDOOR, DEFAULT_DESIGN_OUTDOOR)),
            CONF_RETURN_CEILING: float(store.get(CONF_RETURN_CEILING, DEFAULT_RETURN_CEILING)),
            CONF_DHW_DELTA: float(store.get(CONF_DHW_DELTA, DEFAULT_DHW_DELTA)),
        }
        self._demand_state = DemandCorrectionState()
        self._return_state = ReturnCorrectionState()
        self._manual_hold_state = ManualHoldState()
        self._prev_mode: Mode = Mode.OFF
        super().__init__(hass, _LOGGER, config_entry=entry, name="Boiler Flow Control", update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS))

    # ------------------------------------------------------------------
    # Properties used by entities
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def override(self) -> str:
        return self._override

    @override.setter
    def override(self, value: str) -> None:
        self._override = value

    def get_tunable(self, key: str) -> float:
        return self._tunables[key]

    def set_tunable(self, key: str, value: float) -> None:
        self._tunables[key] = float(value)
        self._store.set(key, float(value))

    def _opt(self, key: str, default: float) -> float:
        return float(self._config.get(key, default))

    # ------------------------------------------------------------------
    # Small HA helpers
    # ------------------------------------------------------------------

    def _state(self, entity_id: str | None):
        return self.hass.states.get(entity_id) if entity_id else None

    def _float_state(self, entity_id: str | None) -> float | None:
        st = self._state(entity_id)
        if st is None or st.state in UNAVAILABLE:
            return None
        try:
            return float(st.state)
        except (ValueError, TypeError):
            return None

    def _is_on(self, entity_id: str | None) -> bool | None:
        """True for binary 'on', or for a numeric sensor above zero (e.g. a relay demand %)."""
        st = self._state(entity_id)
        if st is None or st.state in UNAVAILABLE:
            return None
        if st.state in ("on", "off"):
            return st.state == "on"
        try:
            return float(st.state) > 0.0
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Params
    # ------------------------------------------------------------------

    def _curve_params(self) -> CurveParams:
        return CurveParams(
            design_flow=self._tunables[CONF_DESIGN_FLOW],
            design_outdoor=self._tunables[CONF_DESIGN_OUTDOOR],
            room_design=ROOM_DESIGN_TEMP,
            flow_min=self._opt(CONF_FLOW_MIN, DEFAULT_FLOW_MIN),
            flow_max=self._opt(CONF_FLOW_MAX, DEFAULT_FLOW_MAX),
        )

    def _return_params(self) -> ReturnCeilingParams:
        return ReturnCeilingParams(return_ceiling=self._tunables[CONF_RETURN_CEILING])

    def _dhw_params(self) -> DhwParams:
        return DhwParams(
            dhw_delta=self._tunables[CONF_DHW_DELTA],
            dhw_flow_min=self._opt(CONF_DHW_FLOW_MIN, DEFAULT_DHW_FLOW_MIN),
            dhw_flow_max=self._opt(CONF_DHW_FLOW_MAX, DEFAULT_DHW_FLOW_MAX),
            dhw_return_ceiling=self._opt(CONF_DHW_RETURN_CEILING, DEFAULT_DHW_RETURN_CEILING),
        )

    def _hysteresis_params(self) -> HysteresisParams:
        return HysteresisParams(min_hold_minutes=self._opt(CONF_MIN_HOLD_MINUTES, DEFAULT_MIN_HOLD_MINUTES))

    def _manual_hold_params(self) -> ManualHoldParams:
        return ManualHoldParams(hold_minutes=self._opt(CONF_MANUAL_HOLD_MINUTES, DEFAULT_MANUAL_HOLD_MINUTES))

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------

    async def _perform(self, decision: Decision, max_flow: float | None) -> None:
        if decision.action is not Action.WRITE or decision.setpoint is None:
            return
        entity_id = self._config.get(CONF_FLOW_SETPOINT_ENTITY)
        if not entity_id:
            return
        value = decision.setpoint
        if max_flow is not None:
            value = min(value, max_flow)  # never exceed number.boiler_heatingtemp
        try:
            await self.hass.services.async_call(
                "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=False
            )
            _LOGGER.info("BFC: wrote %.1f to %s (%s)", value, entity_id, decision.reason)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("BFC: number.set_value failed for %s", entity_id)

    # ------------------------------------------------------------------
    # Event-driven ignition counter (change 3)
    # ------------------------------------------------------------------

    def async_subscribe_heating_active(self):
        """Subscribe to state changes of the heating-active binary sensor so
        every off->on transition is counted as an ignition, however close
        together (the boiler can short-cycle faster than the 60 s poll: 6
        starts in 5 min have been observed, which a polled read undercounts).
        Returns the unsubscribe callable, or None if not configured; the
        caller (async_setup_entry) registers it with `entry.async_on_unload`.
        """
        entity_id = self._config.get(CONF_HEATING_ACTIVE_ENTITY)
        if not entity_id:
            return None
        return async_track_state_change_event(self.hass, entity_id, self._handle_heating_active_event)

    def _handle_heating_active_event(self, event) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or new_state.state != "on":
            return
        if old_state is not None and old_state.state == "on":
            return  # not an off->on transition
        now = dt_util.utcnow()
        count = self._hub.record_ignition(now)
        # Update the published snapshot in place. We deliberately do not push a
        # coordinator-wide update from here (no `async_set_updated_data`): the
        # next 60 s poll republishes everything through the normal path, and
        # this keeps the event listener a lightweight, synchronous counter.
        if self.data is not None:
            self.data.cycles_10min = count

    def _maybe_raise_dhw_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "dhw_cycling_unfixable",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="dhw_cycling_unfixable",
        )

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> BFCCoordinatorData:
        try:
            return await self._cycle()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("BFC: update failed")
            if self.data is not None:
                return self.data
            raise UpdateFailed(str(exc)) from exc

    async def _cycle(self) -> BFCCoordinatorData:
        now = dt_util.utcnow()
        cfg = self._config
        d = BFCCoordinatorData(enabled=self._enabled, override=self._override, last_run=now)
        disabled: list[str] = []

        # --- required inputs -------------------------------------------------
        flow_setpoint_entity = cfg.get(CONF_FLOW_SETPOINT_ENTITY)
        live_setpoint_state = self._state(flow_setpoint_entity)
        if flow_setpoint_entity is None or live_setpoint_state is None or live_setpoint_state.state in UNAVAILABLE:
            d.mode = "no_boiler"
            d.no_boiler = True
            d.reason = "ems-esp flow setpoint entity unavailable"
            d.disabled_features = disabled
            return d
        d.live_setpoint = self._float_state(flow_setpoint_entity)

        d.outdoor_temp = self._float_state(cfg.get(CONF_OUTDOOR_TEMP_ENTITY))
        if cfg.get(CONF_OUTDOOR_TEMP_ENTITY) is None or d.outdoor_temp is None:
            disabled.append("heating curve disabled (no outdoor temperature)")

        # --- optional inputs ---------------------------------------------------
        d.current_flow = self._float_state(cfg.get(CONF_CURRENT_FLOW_ENTITY))
        return_raw = self._float_state(cfg.get(CONF_RETURN_TEMP_ENTITY))
        if cfg.get(CONF_RETURN_TEMP_ENTITY) is None:
            disabled.append("return ceiling disabled (no return temperature sensor)")
        d.return_temperature_used, d.return_fresh = self._hub.sample_return(return_raw, now)

        if cfg.get(CONF_HEATING_ACTIVE_ENTITY) is None:
            disabled.append("cycling guard disabled (no heating-active sensor)")
        # Change 3: the ignition counter is event-driven (see async_subscribe_heating_active);
        # the 60 s poll only reads the current window, it no longer feeds it.
        d.cycles_10min = self._hub.cycles_10min(now)

        self._float_state(cfg.get(CONF_BURNER_POWER_ENTITY))  # read for future use / diagnostics only
        if cfg.get(CONF_BURNER_POWER_ENTITY) is None:
            disabled.append("burner power unavailable")

        # --- heating-demand signal (change 1) -----------------------------------
        # The aggregate controller sensor (01_144444_heat_demand) includes stored-
        # hot-water demand: it reads 100 during a DHW-only charge while every
        # per-zone sensor reads 0. Prefer the max of the configured zone sensors
        # (ignoring unavailable ones) so a DHW-only charge does not pollute the
        # heating-side low-pass filter / mode detection; fall back to the
        # aggregate sensor only when no zone list is configured.
        zone_entities: list[str] = cfg.get(CONF_ZONE_DEMAND_ENTITIES) or []
        aggregate_raw = self._float_state(cfg.get(CONF_HEAT_DEMAND_ENTITY))
        d.aggregate_heat_demand = aggregate_raw
        d.zone_max_demand = zone_max_demand([self._float_state(e) for e in zone_entities])
        if not zone_entities and cfg.get(CONF_HEAT_DEMAND_ENTITY) is None:
            disabled.append("heating mode disabled (no aggregate heat-demand sensor)")
        heat_demand_raw = d.zone_max_demand if zone_entities else aggregate_raw
        d.heat_demand = heat_demand_raw
        d.demand_filtered = self._hub.sample_demand(heat_demand_raw, now)

        d.hw_relay_demand = self._float_state(cfg.get(CONF_HW_RELAY_DEMAND_ENTITY))
        if cfg.get(CONF_HW_RELAY_DEMAND_ENTITY) is None:
            disabled.append("DHW mode disabled (no HW relay demand sensor)")

        d.cylinder_temp = self._float_state(cfg.get(CONF_CYLINDER_TEMP_ENTITY))
        if cfg.get(CONF_CYLINDER_TEMP_ENTITY) is None:
            disabled.append("DHW target disabled (no cylinder temperature sensor)")

        d.max_flow = self._float_state(cfg.get(CONF_MAX_FLOW_ENTITY))

        # --- mode inputs ---------------------------------------------------
        heat_demand_bool = bool(d.heat_demand and d.heat_demand > 0)
        relay_dhw_bool = bool(d.hw_relay_demand and d.hw_relay_demand > 0)
        # DHW detection (change 1): relay OR inferred from the aggregate-includes-
        # DHW signature. dhw_and_heating still requires the relay signal — see
        # infer_dhw_demand's docstring and docs/spec.md v0.2 field findings.
        dhw_demand_bool = infer_dhw_demand(
            relay_demand_on=relay_dhw_bool,
            zone_configured=bool(zone_entities),
            aggregate_demand=aggregate_raw,
            zone_max=d.zone_max_demand,
        )

        manual_hold_active, self._manual_hold_state = detect_manual_hold(
            d.live_setpoint, self._hub.last_written_setpoint, d.max_flow, now, self._manual_hold_state, self._manual_hold_params()
        )
        d.manual_hold_active = manual_hold_active

        mode = decide_mode(ModeInputs(
            enabled=self._enabled, heat_demand=heat_demand_bool, dhw_demand=dhw_demand_bool,
            manual_hold_active=manual_hold_active,
        ))

        # --- heating-side physics (always computed: also the DHW-and-heating/idle park value) ---
        curve_params = self._curve_params()
        d.curve = heating_curve(d.outdoor_temp, curve_params) if d.outdoor_temp is not None else None
        self._demand_state = demand_correction_step(self._demand_state, d.demand_filtered, now, DemandCorrectionParams())
        d.demand_correction = self._demand_state.correction
        self._return_state = return_ceiling_step(self._return_state, d.return_temperature_used, d.return_fresh, self._return_params())
        d.return_correction = self._return_state.correction
        d.cycling_correction = cycling_guard_correction(d.cycles_10min, d.demand_filtered, CyclingGuardParams())
        return_over_ceiling = d.return_fresh and d.return_temperature_used is not None and d.return_temperature_used > self._tunables[CONF_RETURN_CEILING]

        heating_value = (
            heating_target(d.outdoor_temp, self._demand_state, self._return_state, d.cycling_correction, curve_params)
            if d.outdoor_temp is not None
            else None
        )

        # --- physical target: DHW wins when it has demand, else heating, else park at curve ---
        dhw_issue_raised = False
        if dhw_demand_bool and d.cylinder_temp is not None:
            target, new_dhw_state, dhw_issue_raised = dhw_target(
                d.cylinder_temp, d.return_temperature_used, d.return_fresh, d.cycles_10min, self._hub.dhw_cycling, self._dhw_params()
            )
            self._hub.set_dhw_cycling(new_dhw_state)
        elif dhw_demand_bool:
            target = heating_value  # demanded but no cylinder reading: fall back to heating value
        else:
            target = heating_value
        d.dhw_issue_raised = dhw_issue_raised
        if dhw_issue_raised:
            self._maybe_raise_dhw_issue()

        # Leaving DHW mode restores the heating value immediately (§3.3.4), exempt from min_hold,
        # like the return ceiling (§3.2.6).
        was_dhw = self._prev_mode in (Mode.DHW, Mode.DHW_AND_HEATING)
        now_dhw = mode in (Mode.DHW, Mode.DHW_AND_HEATING)
        exempt_hysteresis = return_over_ceiling or (was_dhw and not now_dhw)

        memory = self._hub.write_memory()
        decision = decide_write(
            mode, target, Override(self._override), memory, now,
            exempt_hysteresis=exempt_hysteresis, hysteresis_params=self._hysteresis_params(),
        )
        d.mode, d.reason, d.action = mode.value, decision.reason, decision.action.value
        d.flow_setpoint = decision.setpoint if decision.action is Action.WRITE else decision.would_write
        d.would_write = decision.would_write

        await self._perform(decision, d.max_flow)
        if decision.action is Action.WRITE:
            self._hub.record_write(decision.setpoint, now, decision.target_changed)
        d.last_written_setpoint = self._hub.last_written_setpoint
        d.last_write = self._hub.last_written_at
        d.last_target_change = self._hub.last_target_change

        self._prev_mode = mode
        d.disabled_features = disabled
        await self._hub.async_save()
        return d
