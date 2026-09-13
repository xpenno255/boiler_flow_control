"""Boiler Flow Control — dynamic flow-temperature setpoint for ems-esp (phase 1)."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import BFCCoordinator
from .hub import BoilerFlowHub
from .store import BFCStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "switch", "select", "number", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    store = BFCStore(hass, entry.entry_id)
    await store.async_load()

    hub = BoilerFlowHub(store=store)
    hub.load()
    ir.async_delete_issue(hass, DOMAIN, "dhw_cycling_unfixable")

    coordinator = BFCCoordinator(hass, entry, store, hub)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Change 3: event-driven ignition counter, unsubscribed automatically on unload.
    unsub_heating_active = coordinator.async_subscribe_heating_active()
    if unsub_heating_active is not None:
        entry.async_on_unload(unsub_heating_active)

    unsub_dhw = coordinator.async_subscribe_dhw()
    if unsub_dhw is not None:
        entry.async_on_unload(unsub_dhw)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
