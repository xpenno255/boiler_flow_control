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
    ("cycling_status", "Cycling Status", PLAIN, "mdi:sync-alert", True),
    ("dhw_status", "DHW Status", PLAIN, "mdi:water-boiler", True),
    ("last_burn_seconds", "Last Burn Duration", ("s", SensorDeviceClass.DURATION, None), "mdi:fire", True),
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
                "dhw_active": d.dhw_active,
                "dhw_source": d.dhw_source,
                "write_status": d.write_status,
            }
        if self._key == "flow_setpoint":
            return {
                "curve": d.curve,
                "demand_correction": d.demand_correction,
                "return_correction": d.return_correction,
                "cycling_correction": d.cycling_correction,
                "reason": d.reason,
                "would_write": d.would_write,
                "requested_target": d.requested_target,
                "sent_target": d.last_written_setpoint,
                "confirmed_target": d.confirmed_setpoint,
                "write_status": d.write_status,
                "room_correction": d.room_correction,
                "room_error": d.room_error,
            }
        if self._key == "dhw_status":
            return {
                "active": d.dhw_active,
                "source": d.dhw_source,
                "cylinder_target": d.cylinder_target,
                "charge_minutes": d.dhw_charge_minutes,
                "starts_this_charge": d.dhw_charge_starts,
            }
        if self._key == "cycling_status":
            return {
                "starts_10min": d.cycles_10min,
                "last_stop_reason": d.last_stop_reason,
                "burner_power": d.burner_power,
                "last_firing_power": self.coordinator._hub.last_burner_power,
                "current_flow": d.current_flow,
                "live_setpoint": d.live_setpoint,
                "return_temperature": d.return_temperature_used,
                "return_fresh": d.return_fresh,
            }
        if self._key == "return_temperature_used":
            return {"fresh": d.return_fresh}
        if self._key == "last_write":
            return {"last_target_change": d.last_target_change}
        return None
