"""Coordinator integration test: shadow mode computes, auto mode writes once (spec §4)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.boiler_flow_control.const import (
    CONF_CYLINDER_TEMP_ENTITY,
    CONF_FLOW_SETPOINT_ENTITY,
    CONF_HEAT_DEMAND_ENTITY,
    CONF_HW_RELAY_DEMAND_ENTITY,
    CONF_OUTDOOR_TEMP_ENTITY,
    DOMAIN,
    OVERRIDE_AUTO,
    OVERRIDE_SHADOW,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _uid() -> str:
    return f"bfc_{uuid4().hex[:8]}"


async def _setup(hass: HomeAssistant) -> tuple[MockConfigEntry, list]:
    calls: list = []

    async def fake_set_value(call):
        calls.append(dict(call.data))

    hass.states.async_set("number.boiler_selflowtemp", "50")
    hass.states.async_set("sensor.outdoor_temp", "-3")
    hass.states.async_set("sensor.heat_demand", "80")
    hass.states.async_set("sensor.hw_relay_demand", "0")

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler Flow Control", entry_id=_uid(),
        data={
            CONF_FLOW_SETPOINT_ENTITY: "number.boiler_selflowtemp",
            CONF_OUTDOOR_TEMP_ENTITY: "sensor.outdoor_temp",
            CONF_HEAT_DEMAND_ENTITY: "sensor.heat_demand",
            CONF_HW_RELAY_DEMAND_ENTITY: "sensor.hw_relay_demand",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # Loading our own `number` platform pulls in the real number component and its
    # own `number.set_value` service; override it here, after setup, to capture calls.
    hass.services.async_register("number", "set_value", fake_set_value)
    return entry, calls


async def test_shadow_mode_computes_and_writes_nothing(hass: HomeAssistant):
    entry, calls = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.override == OVERRIDE_SHADOW  # default per spec §4
    d = coordinator.data
    assert d.mode == "heating"
    assert d.curve == pytest.approx(55.0)  # design flow at design outdoor
    assert d.would_write is not None
    assert calls == []
    st = hass.states.get("sensor.boiler_flow_control_mode")
    assert st is not None and st.state == "heating"


async def test_auto_mode_writes_once_then_holds(hass: HomeAssistant):
    entry, calls = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.override = OVERRIDE_AUTO
    await coordinator.async_refresh()
    assert len(calls) == 1
    assert calls[0]["entity_id"] == "number.boiler_selflowtemp"
    first_value = calls[0]["value"]

    await coordinator.async_refresh()
    assert len(calls) == 1, "unchanged value must not be rewritten inside min_hold"
    assert coordinator.data.flow_setpoint == pytest.approx(first_value)


async def test_no_boiler_when_flow_setpoint_entity_unavailable(hass: HomeAssistant):
    entry, calls = await _setup(hass)
    coordinator = entry.runtime_data
    hass.states.async_set("number.boiler_selflowtemp", "unavailable")
    await coordinator.async_refresh()
    assert coordinator.data.no_boiler is True
    assert coordinator.data.mode == "no_boiler"
    assert calls == []


async def test_missing_optional_entities_are_reported_disabled(hass: HomeAssistant):
    entry, calls = await _setup(hass)
    coordinator = entry.runtime_data
    d = coordinator.data
    assert any("return ceiling disabled" in f for f in d.disabled_features)
    assert any("cycling guard disabled" in f for f in d.disabled_features)
