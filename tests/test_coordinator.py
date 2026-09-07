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
    CONF_HEATING_ACTIVE_ENTITY,
    CONF_HW_RELAY_DEMAND_ENTITY,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_ZONE_DEMAND_ENTITIES,
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
        # Mirror real ems-esp/number-entity behaviour: the live state reflects
        # what was just written, so manual-hold detection sees the value we
        # actually wrote, not a stale live reading.
        hass.states.async_set(call.data["entity_id"], call.data["value"])

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


async def test_auto_mode_re_asserts_every_cycle(hass: HomeAssistant):
    # Change 2: ems-esp decays a written flow setpoint back to the dial value
    # within ~2 min of nothing rewriting it, so auto mode must call
    # number.set_value every cycle even when the target has not changed.
    entry, calls = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.override = OVERRIDE_AUTO
    await coordinator.async_refresh()
    assert len(calls) == 1
    assert calls[0]["entity_id"] == "number.boiler_selflowtemp"
    first_value = calls[0]["value"]

    await coordinator.async_refresh()
    assert len(calls) == 2, "auto mode must re-assert the target every cycle"
    assert calls[1]["value"] == pytest.approx(first_value)
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


# --- change 1: zone-demand heating signal and DHW inference -----------------


async def _setup_with_zones(hass: HomeAssistant) -> tuple[MockConfigEntry, list]:
    calls: list = []

    async def fake_set_value(call):
        calls.append(dict(call.data))
        # Mirror real ems-esp/number-entity behaviour: the live state reflects
        # what was just written, so manual-hold detection sees the value we
        # actually wrote, not a stale live reading.
        hass.states.async_set(call.data["entity_id"], call.data["value"])

    hass.states.async_set("number.boiler_selflowtemp", "50")
    hass.states.async_set("sensor.outdoor_temp", "-3")
    hass.states.async_set("sensor.heat_demand", "100")  # aggregate: includes DHW
    hass.states.async_set("sensor.hw_relay_demand", "0")  # relay missed this charge
    hass.states.async_set("sensor.zone_1_demand", "0")
    hass.states.async_set("sensor.zone_2_demand", "unavailable")

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler Flow Control", entry_id=_uid(),
        data={
            CONF_FLOW_SETPOINT_ENTITY: "number.boiler_selflowtemp",
            CONF_OUTDOOR_TEMP_ENTITY: "sensor.outdoor_temp",
            CONF_HEAT_DEMAND_ENTITY: "sensor.heat_demand",
            CONF_HW_RELAY_DEMAND_ENTITY: "sensor.hw_relay_demand",
            CONF_ZONE_DEMAND_ENTITIES: ["sensor.zone_1_demand", "sensor.zone_2_demand"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.services.async_register("number", "set_value", fake_set_value)
    return entry, calls


async def test_dhw_only_charge_inferred_from_zone_max_and_aggregate(hass: HomeAssistant):
    entry, calls = await _setup_with_zones(hass)
    coordinator = entry.runtime_data
    d = coordinator.data
    assert d.zone_max_demand == 0.0  # unavailable zone ignored, both effectively 0
    assert d.aggregate_heat_demand == pytest.approx(100.0)
    assert d.heat_demand == 0.0  # heating-side signal is the zone max, not the aggregate
    assert d.mode == "dhw"  # inferred despite the relay reading 0


async def test_genuine_heating_demand_not_mistaken_for_dhw(hass: HomeAssistant):
    entry, calls = await _setup_with_zones(hass)
    hass.states.async_set("sensor.zone_1_demand", "40")
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    d = coordinator.data
    assert d.zone_max_demand == pytest.approx(40.0)
    assert d.heat_demand == pytest.approx(40.0)
    assert d.mode == "heating"  # zone_max != 0, so DHW is not inferred


# --- change 3: event-driven ignition counter --------------------------------


async def test_ignition_counter_counts_sub_minute_state_changes(hass: HomeAssistant):
    hass.states.async_set("number.boiler_selflowtemp", "50")
    hass.states.async_set("sensor.outdoor_temp", "-3")
    hass.states.async_set("sensor.heat_demand", "80")
    hass.states.async_set("sensor.hw_relay_demand", "0")
    hass.states.async_set("binary_sensor.heating_active", "off")

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler Flow Control", entry_id=_uid(),
        data={
            CONF_FLOW_SETPOINT_ENTITY: "number.boiler_selflowtemp",
            CONF_OUTDOOR_TEMP_ENTITY: "sensor.outdoor_temp",
            CONF_HEAT_DEMAND_ENTITY: "sensor.heat_demand",
            CONF_HW_RELAY_DEMAND_ENTITY: "sensor.hw_relay_demand",
            CONF_HEATING_ACTIVE_ENTITY: "binary_sensor.heating_active",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    # Two off->on transitions closer together than the 60 s poll interval.
    for _ in range(2):
        hass.states.async_set("binary_sensor.heating_active", "on")
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.heating_active", "off")
        await hass.async_block_till_done()

    assert coordinator.data.cycles_10min == 2

    ok = await hass.config_entries.async_unload(entry.entry_id)
    assert ok
    # No error subscribing after unload; further state changes are ignored.
    hass.states.async_set("binary_sensor.heating_active", "on")
    await hass.async_block_till_done()
