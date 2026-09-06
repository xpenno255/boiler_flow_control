"""Config and options flow for Boiler Flow Control (single hub-style entry, §4, §5)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_BURNER_POWER_ENTITY,
    CONF_CURRENT_FLOW_ENTITY,
    CONF_CYLINDER_TEMP_ENTITY,
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
    CONF_RETURN_TEMP_ENTITY,
    DEFAULT_DHW_FLOW_MAX,
    DEFAULT_DHW_FLOW_MIN,
    DEFAULT_DHW_RETURN_CEILING,
    DEFAULT_FLOW_MAX,
    DEFAULT_FLOW_MIN,
    DEFAULT_MANUAL_HOLD_MINUTES,
    DEFAULT_MIN_HOLD_MINUTES,
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
        if key in flat and (flat[key] is None or flat[key] == ""):
            flat.pop(key)
    return flat


def entities_schema(d: dict[str, Any] | None = None) -> vol.Schema:
    d = d or {}
    return vol.Schema(
        {
            vol.Required(CONF_FLOW_SETPOINT_ENTITY, default=d.get(CONF_FLOW_SETPOINT_ENTITY, "")): _entity("number"),
            vol.Required(CONF_OUTDOOR_TEMP_ENTITY, default=d.get(CONF_OUTDOOR_TEMP_ENTITY, "")): _entity("sensor"),
            vol.Optional("optional_section"): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_CURRENT_FLOW_ENTITY, description={"suggested_value": d.get(CONF_CURRENT_FLOW_ENTITY)}): _entity("sensor"),
                        vol.Optional(CONF_RETURN_TEMP_ENTITY, description={"suggested_value": d.get(CONF_RETURN_TEMP_ENTITY)}): _entity("sensor"),
                        vol.Optional(CONF_HEATING_ACTIVE_ENTITY, description={"suggested_value": d.get(CONF_HEATING_ACTIVE_ENTITY)}): _entity("binary_sensor"),
                        vol.Optional(CONF_BURNER_POWER_ENTITY, description={"suggested_value": d.get(CONF_BURNER_POWER_ENTITY)}): _entity("sensor"),
                        vol.Optional(CONF_HEAT_DEMAND_ENTITY, description={"suggested_value": d.get(CONF_HEAT_DEMAND_ENTITY)}): _entity("sensor"),
                        vol.Optional(CONF_HW_RELAY_DEMAND_ENTITY, description={"suggested_value": d.get(CONF_HW_RELAY_DEMAND_ENTITY)}): _entity("sensor"),
                        vol.Optional(CONF_CYLINDER_TEMP_ENTITY, description={"suggested_value": d.get(CONF_CYLINDER_TEMP_ENTITY)}): _entity("sensor"),
                        vol.Optional(CONF_MAX_FLOW_ENTITY, description={"suggested_value": d.get(CONF_MAX_FLOW_ENTITY)}): _entity("number"),
                    }
                )
            ),
            vol.Optional("tunables_section"): section(
                vol.Schema(
                    {
                        vol.Required(CONF_FLOW_MIN, default=d.get(CONF_FLOW_MIN, DEFAULT_FLOW_MIN)): _num(20, 60, 1, "°C"),
                        vol.Required(CONF_FLOW_MAX, default=d.get(CONF_FLOW_MAX, DEFAULT_FLOW_MAX)): _num(40, 80, 1, "°C"),
                        vol.Required(CONF_DHW_FLOW_MIN, default=d.get(CONF_DHW_FLOW_MIN, DEFAULT_DHW_FLOW_MIN)): _num(40, 80, 1, "°C"),
                        vol.Required(CONF_DHW_FLOW_MAX, default=d.get(CONF_DHW_FLOW_MAX, DEFAULT_DHW_FLOW_MAX)): _num(40, 85, 1, "°C"),
                        vol.Required(CONF_DHW_RETURN_CEILING, default=d.get(CONF_DHW_RETURN_CEILING, DEFAULT_DHW_RETURN_CEILING)): _num(40, 85, 1, "°C"),
                        vol.Required(CONF_MIN_HOLD_MINUTES, default=d.get(CONF_MIN_HOLD_MINUTES, DEFAULT_MIN_HOLD_MINUTES)): _num(1, 60, 1, "min"),
                        vol.Required(CONF_MANUAL_HOLD_MINUTES, default=d.get(CONF_MANUAL_HOLD_MINUTES, DEFAULT_MANUAL_HOLD_MINUTES)): _num(1, 240, 5, "min"),
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
            return self.async_create_entry(title="Boiler Flow Control", data=flat)
        return self.async_show_form(step_id="user", data_schema=entities_schema())

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry):
        return BFCOptionsFlow()


class BFCOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_ENTITY_KEYS)
            return self.async_create_entry(title="", data=flat)
        return self.async_show_form(step_id="init", data_schema=entities_schema(current))
