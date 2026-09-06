"""Enable switch for Boiler Flow Control (§4)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import BFCCoordinator
from .entity import BFCEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BFCCoordinator = entry.runtime_data
    async_add_entities([BFCEnableSwitch(coordinator, entry)])


class BFCEnableSwitch(BFCEntity, SwitchEntity, RestoreEntity):
    _attr_name = "Enabled"
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.coordinator.enabled = last.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.enabled = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.enabled = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
