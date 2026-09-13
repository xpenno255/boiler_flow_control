"""Configuration validity and migration of previously persisted fault states."""

import pytest

from custom_components.boiler_flow_control.config_flow import _validate_ranges
from custom_components.boiler_flow_control.hub import BoilerFlowHub
from custom_components.boiler_flow_control.store import BFCStore


@pytest.mark.parametrize(
    ("config", "error"),
    [
        ({"flow_min": 60, "flow_max": 40}, "flow_max"),
        ({"dhw_flow_min": 75, "dhw_flow_max": 70}, "dhw_flow_max"),
        ({"dhw_fallback_flow": 90}, "dhw_fallback_flow"),
        ({"dhw_target": 65, "dhw_flow_max": 65}, "dhw_flow_max"),
        ({"dhw_progress_minutes": 90, "dhw_timeout_minutes": 60}, "dhw_timeout_minutes"),
    ],
)
def test_invalid_operating_ranges_are_rejected(config, error):
    assert error in _validate_ranges(config)


def test_valid_operating_ranges():
    assert not _validate_ranges({"dhw_target": 60, "dhw_flow_max": 70, "dhw_fallback_flow": 70})


def test_upgrade_clears_legacy_hold_and_inaccurate_write_memory(hass):
    store = BFCStore(hass, "upgrade_test")
    store.set("dhw_cycling_holding", True)
    store.set("dhw_cycling_attempts", 2)
    store.set("last_written_setpoint", 55)
    hub = BoilerFlowHub(store=store)
    hub.load()
    assert not hub.dhw_cycling.holding
    assert hub.dhw_cycling.attempts == 0
    assert hub.last_written_setpoint is None


def test_v3_keeps_effective_write_memory(hass):
    store = BFCStore(hass, "upgrade_test")
    store.set("control_version", 3)
    store.set("last_written_setpoint", 50)
    hub = BoilerFlowHub(store=store)
    hub.load()
    assert hub.last_written_setpoint == 50


async def test_overlapping_saves_preserve_latest_complete_state(hass):
    import asyncio

    store = BFCStore(hass, "concurrent_save_test")

    async def save(value):
        store.set("value", value)
        await store.async_save()

    await asyncio.gather(*(save(value) for value in range(5)))
    restored = BFCStore(hass, "concurrent_save_test")
    assert (await restored.async_load())["value"] == 4
