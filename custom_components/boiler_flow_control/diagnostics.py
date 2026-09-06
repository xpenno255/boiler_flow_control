"""Diagnostics for Boiler Flow Control."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DESIGN_FLOW, CONF_DESIGN_OUTDOOR, CONF_DHW_DELTA, CONF_RETURN_CEILING


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    config = {**entry.data, **entry.options}
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "config": config,
        "enabled": coordinator.enabled,
        "override": coordinator.override,
        "tunables": {k: coordinator.get_tunable(k) for k in (CONF_DESIGN_FLOW, CONF_DESIGN_OUTDOOR, CONF_RETURN_CEILING, CONF_DHW_DELTA)},
        "store": coordinator._store._data,  # noqa: SLF001
        "last_cycle": None if data is None else {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in asdict(data).items()},
    }
