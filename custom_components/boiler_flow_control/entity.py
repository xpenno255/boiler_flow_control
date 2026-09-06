"""Shared entity base class."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BFCCoordinator, BFCCoordinatorData

VERSION = "0.1.0"


class BFCEntity(CoordinatorEntity[BFCCoordinator]):
    """Base for all Boiler Flow Control entities (single hub-style entry)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BFCCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Boiler Flow Control",
            manufacturer="Boiler Flow Control",
            model=VERSION,
        )

    @property
    def snapshot(self) -> BFCCoordinatorData | None:
        return self.coordinator.data
