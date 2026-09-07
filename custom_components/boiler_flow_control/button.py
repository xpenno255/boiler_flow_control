"""Button: reset the sticky DHW cycling hold (v0.2.1 review fix 3c).

The DHW cycling guard's hold is sticky by design (§3.3.3): once the coil/pump/
min-power issue has been addressed, this button clears the hold + attempts and
deletes the repair issue so auto operation resumes without a restart.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BFCCoordinator
from .entity import BFCEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BFCCoordinator = entry.runtime_data
    async_add_entities([BFCResetDhwCyclingButton(coordinator, entry)])


class BFCResetDhwCyclingButton(BFCEntity, ButtonEntity):
    _attr_name = "Reset DHW cycling hold"
    _attr_icon = "mdi:refresh-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "reset_dhw_cycling")

    async def async_press(self) -> None:
        await self.coordinator.async_reset_dhw_cycling()
