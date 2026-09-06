"""Live tunable numbers (§4): design flow, design outdoor, return ceiling, DHW delta."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DESIGN_FLOW, CONF_DESIGN_OUTDOOR, CONF_DHW_DELTA, CONF_RETURN_CEILING
from .coordinator import BFCCoordinator
from .entity import BFCEntity

# key, name, min, max, step, unit, icon
NUMBERS = [
    (CONF_DESIGN_FLOW, "Design Flow", 30.0, 80.0, 1.0, "°C", "mdi:thermometer-lines"),
    (CONF_DESIGN_OUTDOOR, "Design Outdoor", -15.0, 10.0, 0.5, "°C", "mdi:snowflake-thermometer"),
    (CONF_RETURN_CEILING, "Return Ceiling", 30.0, 70.0, 1.0, "°C", "mdi:arrow-collapse-down"),
    (CONF_DHW_DELTA, "DHW Delta", 5.0, 40.0, 1.0, "K", "mdi:delta"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BFCCoordinator = entry.runtime_data
    async_add_entities(BFCNumber(coordinator, entry, *spec) for spec in NUMBERS)


class BFCNumber(BFCEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, key, name, mn, mx, step, unit, icon) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def native_value(self) -> float:
        return self.coordinator.get_tunable(self._key)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_tunable(self._key, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
