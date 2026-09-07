"""Sensors for Boiler Flow Control (§4)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BFCCoordinator
from .entity import BFCEntity

TEMP = ("°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT)
PLAIN = (None, None, None)
COUNT = (None, None, SensorStateClass.MEASUREMENT)
PERCENT = ("%", None, SensorStateClass.MEASUREMENT)

# key, name, (unit, device_class, state_class), icon, diagnostic?
SENSORS: list[tuple[str, str, tuple, str | None, bool]] = [
    ("mode", "Mode", PLAIN, "mdi:state-machine", False),
    ("flow_setpoint", "Flow Setpoint", TEMP, "mdi:thermometer-water", False),
    ("return_temperature_used", "Return Temperature Used", TEMP, None, True),
    ("cycles_10min", "Cycles (10 min)", COUNT, "mdi:sync-alert", True),
    ("demand_filtered", "Heat Demand Filtered", PERCENT, "mdi:radiator", True),
    ("last_write", "Last Write", (None, SensorDeviceClass.TIMESTAMP, None), None, True),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BFCCoordinator = entry.runtime_data
    async_add_entities(BFCSensor(coordinator, entry, *spec) for spec in SENSORS)


class BFCSensor(BFCEntity, SensorEntity):
    def __init__(self, coordinator, entry, key, name, spec, icon, diagnostic) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement, self._attr_device_class, self._attr_state_class = spec
        self._attr_icon = icon
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        d = self.snapshot
        return None if d is None else getattr(d, self._key, None)

    @property
    def extra_state_attributes(self):
        d = self.snapshot
        if d is None:
            return None
        if self._key == "mode":
            return {
                "reason": d.reason,
                "action": d.action,
                "enabled": d.enabled,
                "override": d.override,
                "no_boiler": d.no_boiler,
                "manual_hold_active": d.manual_hold_active,
                "dhw_issue_raised": d.dhw_issue_raised,
                "disabled_features": d.disabled_features,
                "aggregate_heat_demand": d.aggregate_heat_demand,
                "zone_max_demand": d.zone_max_demand,
            }
        if self._key == "flow_setpoint":
            return {
                "curve": d.curve,
                "demand_correction": d.demand_correction,
                "return_correction": d.return_correction,
                "cycling_correction": d.cycling_correction,
                "reason": d.reason,
                "would_write": d.would_write,
            }
        if self._key == "return_temperature_used":
            return {"fresh": d.return_fresh}
        if self._key == "last_write":
            return {"last_target_change": d.last_target_change}
        return None
