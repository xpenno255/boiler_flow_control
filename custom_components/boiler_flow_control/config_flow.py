"""Config and options flow for Boiler Flow Control (single hub-style entry, §4, §5)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_BOILER_RELAY_ENTITY,
    CONF_BURNER_POWER_ENTITY,
    CONF_CURRENT_FLOW_ENTITY,
    CONF_CYLINDER_TARGET_ENTITY,
    CONF_CYLINDER_TEMP_ENTITY,
    CONF_DHW_FALLBACK_FLOW,
    CONF_DHW_FLOW_MAX,
    CONF_DHW_FLOW_MIN,
    CONF_DHW_PROGRESS_MINUTES,
    CONF_DHW_TARGET,
    CONF_DHW_TIMEOUT_MINUTES,
    CONF_FLOW_MAX,
    CONF_FLOW_MIN,
    CONF_FLOW_SETPOINT_ENTITY,
    CONF_HEAT_DEMAND_ENTITY,
    CONF_HEATING_ACTIVE_ENTITY,
    CONF_HW_RELAY_DEMAND_ENTITY,
    CONF_INPUT_FRESHNESS_MINUTES,
    CONF_MANUAL_HOLD_MINUTES,
    CONF_MAX_FLOW_ENTITY,
    CONF_MIN_HOLD_MINUTES,
    CONF_OUTDOOR_FRESHNESS_MINUTES,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_RETURN_TEMP_ENTITY,
    CONF_ROOM_CLIMATE_ENTITIES,
    CONF_ZONE_DEMAND_ENTITIES,
    DEFAULT_DHW_FLOW_MAX,
    DEFAULT_DHW_FLOW_MIN,
    DEFAULT_DHW_PROGRESS_MINUTES,
    DEFAULT_DHW_TARGET,
    DEFAULT_DHW_TIMEOUT_MINUTES,
    DEFAULT_FLOW_MAX,
    DEFAULT_FLOW_MIN,
    DEFAULT_INPUT_FRESHNESS_MINUTES,
    DEFAULT_MANUAL_HOLD_MINUTES,
    DEFAULT_MIN_HOLD_MINUTES,
    DEFAULT_OUTDOOR_FRESHNESS_MINUTES,
    DOMAIN,
    OPTIONAL_ENTITY_KEYS,
)


def _entity(domain: str | list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _num(mn: float, mx: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    cfg = selector.NumberSelectorConfig(min=mn, max=mx, step=step, mode=selector.NumberSelectorMode.BOX)
    if unit:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(cfg)


def _flatten(user_input: dict) -> dict:
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict) and key.endswith("_section"):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _strip_empty(flat: dict, keys: tuple[str, ...]) -> dict:
    for key in keys:
        if key in flat and (flat[key] is None or flat[key] == "" or flat[key] == []):
            flat.pop(key)
    return flat


def _validate_ranges(flat: dict) -> dict[str, str]:
    """v0.2.1 review fix 10: reject flow_min > flow_max and dhw_flow_min >
    dhw_flow_max with a form error instead of silently accepting an inverted
    range."""
    errors: dict[str, str] = {}
    flow_min, flow_max = flat.get(CONF_FLOW_MIN), flat.get(CONF_FLOW_MAX)
    if flow_min is not None and flow_max is not None and flow_min > flow_max:
        errors[CONF_FLOW_MAX] = "flow_min_above_max"
    dhw_min, dhw_max = flat.get(CONF_DHW_FLOW_MIN), flat.get(CONF_DHW_FLOW_MAX)
    if dhw_min is not None and dhw_max is not None and dhw_min > dhw_max:
        errors[CONF_DHW_FLOW_MAX] = "dhw_flow_min_above_max"
    fallback = flat.get(CONF_DHW_FALLBACK_FLOW)
    if fallback is not None and not (
        flat.get(CONF_DHW_FLOW_MIN, DEFAULT_DHW_FLOW_MIN)
        <= fallback
        <= flat.get(CONF_DHW_FLOW_MAX, DEFAULT_DHW_FLOW_MAX)
    ):
        errors[CONF_DHW_FALLBACK_FLOW] = "fallback_outside_range"
    target = flat.get(CONF_DHW_TARGET, DEFAULT_DHW_TARGET)
    if flat.get(CONF_DHW_FLOW_MAX, DEFAULT_DHW_FLOW_MAX) < target + 5:
        errors.setdefault(CONF_DHW_FLOW_MAX, "insufficient_dhw_headroom")
    if flat.get(CONF_DHW_TIMEOUT_MINUTES, DEFAULT_DHW_TIMEOUT_MINUTES) < flat.get(
        CONF_DHW_PROGRESS_MINUTES, DEFAULT_DHW_PROGRESS_MINUTES
    ):
        errors[CONF_DHW_TIMEOUT_MINUTES] = "timeout_before_progress"
    return errors


def entities_schema(d: dict[str, Any] | None = None) -> vol.Schema:
    d = d or {}
    return vol.Schema(
        {
            vol.Required(CONF_FLOW_SETPOINT_ENTITY, default=d.get(CONF_FLOW_SETPOINT_ENTITY, "")): _entity("number"),
            vol.Required(CONF_OUTDOOR_TEMP_ENTITY, default=d.get(CONF_OUTDOOR_TEMP_ENTITY, "")): _entity("sensor"),
            vol.Optional("optional_section"): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_CYLINDER_TARGET_ENTITY,
                            description={"suggested_value": d.get(CONF_CYLINDER_TARGET_ENTITY)},
                        ): _entity(["sensor", "number", "climate", "water_heater"]),
                        vol.Optional(
                            CONF_ROOM_CLIMATE_ENTITIES,
                            description={"suggested_value": d.get(CONF_ROOM_CLIMATE_ENTITIES)},
                        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate", multiple=True)),
                        vol.Optional(
                            CONF_BOILER_RELAY_ENTITY, description={"suggested_value": d.get(CONF_BOILER_RELAY_ENTITY)}
                        ): _entity(["sensor", "binary_sensor", "switch"]),
                        vol.Optional(
                            CONF_CURRENT_FLOW_ENTITY, description={"suggested_value": d.get(CONF_CURRENT_FLOW_ENTITY)}
                        ): _entity("sensor"),
                        vol.Optional(
                            CONF_RETURN_TEMP_ENTITY, description={"suggested_value": d.get(CONF_RETURN_TEMP_ENTITY)}
                        ): _entity("sensor"),
                        vol.Optional(
                            CONF_HEATING_ACTIVE_ENTITY,
                            description={"suggested_value": d.get(CONF_HEATING_ACTIVE_ENTITY)},
                        ): _entity("binary_sensor"),
                        vol.Optional(
                            CONF_BURNER_POWER_ENTITY, description={"suggested_value": d.get(CONF_BURNER_POWER_ENTITY)}
                        ): _entity("sensor"),
                        vol.Optional(
                            CONF_HEAT_DEMAND_ENTITY, description={"suggested_value": d.get(CONF_HEAT_DEMAND_ENTITY)}
                        ): _entity("sensor"),
                        vol.Optional(
                            CONF_HW_RELAY_DEMAND_ENTITY,
                            description={"suggested_value": d.get(CONF_HW_RELAY_DEMAND_ENTITY)},
                        ): _entity("sensor"),
                        vol.Optional(
                            CONF_CYLINDER_TEMP_ENTITY, description={"suggested_value": d.get(CONF_CYLINDER_TEMP_ENTITY)}
                        ): _entity("sensor"),
                        vol.Optional(
                            CONF_MAX_FLOW_ENTITY, description={"suggested_value": d.get(CONF_MAX_FLOW_ENTITY)}
                        ): _entity("number"),
                        vol.Optional(
                            CONF_ZONE_DEMAND_ENTITIES, description={"suggested_value": d.get(CONF_ZONE_DEMAND_ENTITIES)}
                        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", multiple=True)),
                    }
                )
            ),
            vol.Optional("tunables_section"): section(
                vol.Schema(
                    {
                        vol.Required(CONF_FLOW_MIN, default=d.get(CONF_FLOW_MIN, DEFAULT_FLOW_MIN)): _num(
                            20, 60, 1, "°C"
                        ),
                        vol.Required(CONF_FLOW_MAX, default=d.get(CONF_FLOW_MAX, DEFAULT_FLOW_MAX)): _num(
                            40, 80, 1, "°C"
                        ),
                        vol.Required(CONF_DHW_FLOW_MIN, default=d.get(CONF_DHW_FLOW_MIN, DEFAULT_DHW_FLOW_MIN)): _num(
                            40, 80, 1, "°C"
                        ),
                        vol.Required(CONF_DHW_FLOW_MAX, default=d.get(CONF_DHW_FLOW_MAX, DEFAULT_DHW_FLOW_MAX)): _num(
                            40, 85, 1, "°C"
                        ),
                        vol.Required(CONF_DHW_TARGET, default=d.get(CONF_DHW_TARGET, DEFAULT_DHW_TARGET)): _num(
                            40, 80, 1, "°C"
                        ),
                        vol.Required(
                            CONF_DHW_FALLBACK_FLOW,
                            default=d.get(CONF_DHW_FALLBACK_FLOW, d.get(CONF_DHW_FLOW_MAX, DEFAULT_DHW_FLOW_MAX)),
                        ): _num(40, 85, 1, "°C"),
                        vol.Required(
                            CONF_DHW_PROGRESS_MINUTES,
                            default=d.get(CONF_DHW_PROGRESS_MINUTES, DEFAULT_DHW_PROGRESS_MINUTES),
                        ): _num(10, 120, 5, "min"),
                        vol.Required(
                            CONF_DHW_TIMEOUT_MINUTES,
                            default=d.get(CONF_DHW_TIMEOUT_MINUTES, DEFAULT_DHW_TIMEOUT_MINUTES),
                        ): _num(30, 240, 5, "min"),
                        vol.Required(
                            CONF_INPUT_FRESHNESS_MINUTES,
                            default=d.get(CONF_INPUT_FRESHNESS_MINUTES, DEFAULT_INPUT_FRESHNESS_MINUTES),
                        ): _num(5, 120, 5, "min"),
                        vol.Required(
                            CONF_OUTDOOR_FRESHNESS_MINUTES,
                            default=d.get(CONF_OUTDOOR_FRESHNESS_MINUTES, DEFAULT_OUTDOOR_FRESHNESS_MINUTES),
                        ): _num(15, 240, 15, "min"),
                        vol.Required(
                            CONF_MIN_HOLD_MINUTES, default=d.get(CONF_MIN_HOLD_MINUTES, DEFAULT_MIN_HOLD_MINUTES)
                        ): _num(1, 60, 1, "min"),
                        vol.Required(
                            CONF_MANUAL_HOLD_MINUTES,
                            default=d.get(CONF_MANUAL_HOLD_MINUTES, DEFAULT_MANUAL_HOLD_MINUTES),
                        ): _num(1, 240, 5, "min"),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


class BFCConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        for entry in self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_ENTITY_KEYS)
            errors = _validate_ranges(flat)
            if errors:
                return self.async_show_form(step_id="user", data_schema=entities_schema(flat), errors=errors)
            return self.async_create_entry(title="Boiler Flow Control", data=flat)
        return self.async_show_form(step_id="user", data_schema=entities_schema())

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry):
        return BFCOptionsFlow()


class BFCOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        current = dict(self.config_entry.options) if self.config_entry.options else dict(self.config_entry.data)
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_ENTITY_KEYS)
            errors = _validate_ranges(flat)
            if errors:
                return self.async_show_form(step_id="init", data_schema=entities_schema(flat), errors=errors)
            return self.async_create_entry(title="", data=flat)
        return self.async_show_form(step_id="init", data_schema=entities_schema(current))
