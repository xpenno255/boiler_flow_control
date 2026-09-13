"""A shared DHW signal for companion integrations and automations."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import BFCEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BFCDhwActive(entry.runtime_data, entry)])


class BFCDhwActive(BFCEntity, BinarySensorEntity):
    _attr_name = "DHW Active"
    _attr_icon = "mdi:water-boiler"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "dhw_active")

    @property
    def is_on(self):
        return self.snapshot.dhw_active if self.snapshot else None

    @property
    def extra_state_attributes(self):
        d = self.snapshot
        return {"source": d.dhw_source, "mode": d.mode} if d else None
