"""Historical reproduction: run only against baseline c3a80a6, not v0.3+."""
from datetime import timedelta
import pytest
from homeassistant.util import dt as dt_util
from test_coordinator import _setup, auto_enable_custom_integrations
from custom_components.boiler_flow_control.const import *
from custom_components.boiler_flow_control.core.model import *
from custom_components.boiler_flow_control.core.curve import dhw_target, demand_correction_step, return_ceiling_step
from custom_components.boiler_flow_control.core.policy import infer_dhw_demand, zone_max_demand

pytestmark = pytest.mark.asyncio

async def test_dhw_entry_holds_old_heating_target(hass):
    entry, calls = await _setup(hass)
    c = entry.runtime_data
    c.override = OVERRIDE_AUTO
    await c.async_refresh()
    c._config[CONF_CYLINDER_TEMP_ENTITY] = 'sensor.cylinder'
    hass.states.async_set('sensor.cylinder', '50')
    hass.states.async_set('sensor.hw_relay_demand', '100')
    await c.async_refresh()
    assert c.data.mode == 'dhw_and_heating'
    assert c.data.would_write == 70
    assert calls[-1]['value'] == 55
    print('DHW entry: proposed 70 C, sent 55 C')

async def test_guard_counts_unapplied_attempts(hass):
    entry, calls = await _setup(hass)
    c = entry.runtime_data
    c.override = OVERRIDE_AUTO
    c._config[CONF_CYLINDER_TEMP_ENTITY] = 'sensor.cylinder'
    hass.states.async_set('sensor.cylinder', '50')
    hass.states.async_set('sensor.hw_relay_demand', '100')
    await c.async_refresh()
    assert calls[-1]['value'] == 70
    for _ in range(3): c._hub.record_ignition(dt_util.utcnow())
    await c.async_refresh()
    assert c._hub.dhw_cycling.attempts == 1
    assert c.data.would_write == 65
    assert calls[-1]['value'] == 70
    for _ in range(3): c._hub.record_ignition(dt_util.utcnow())
    await c.async_refresh()
    assert c._hub.dhw_cycling.holding
    assert calls[-1]['value'] == 70
    print('DHW hold reached without ever sending the first 65 C intervention')

async def test_missing_cylinder_uses_heating_curve(hass):
    entry, calls = await _setup(hass)
    c = entry.runtime_data
    c.override = OVERRIDE_AUTO
    hass.states.async_set('sensor.outdoor_temp', '15')
    hass.states.async_set('sensor.hw_relay_demand', '100')
    await c.async_refresh()
    assert c.data.mode == 'dhw_and_heating'
    assert calls[-1]['value'] == 35
    print('DHW demand without cylinder sensor: sent 35 C')

async def test_capped_write_memory_diverges(hass):
    entry, calls = await _setup(hass)
    c = entry.runtime_data
    c.override = OVERRIDE_AUTO
    c._config[CONF_MAX_FLOW_ENTITY] = 'number.max_flow'
    hass.states.async_set('number.max_flow', '50')
    await c.async_refresh()
    assert calls[-1]['value'] == 50
    assert c._hub.last_written_setpoint == 55
    hass.states.async_set('number.max_flow', '70')
    await c.async_refresh()
    assert c.data.mode == 'manual_hold'
    print('Sent 50 C, remembered 55 C; raising dial causes false manual hold')

async def test_heating_ignitions_count_against_new_dhw_charge(hass):
    entry, calls = await _setup(hass)
    c = entry.runtime_data
    c.override = OVERRIDE_AUTO
    await c.async_refresh()
    for _ in range(3): c._hub.record_ignition(dt_util.utcnow())
    c._config[CONF_CYLINDER_TEMP_ENTITY] = 'sensor.cylinder'
    hass.states.async_set('sensor.cylinder', '50')
    hass.states.async_set('sensor.hw_relay_demand', '100')
    await c.async_refresh()
    assert c._hub.dhw_cycling.attempts == 1
    print('New DHW charge gets a cycling intervention from earlier heating starts')

async def test_idle_preserves_sustain_timer():
    now = dt_util.utcnow()
    state = DemandCorrectionState(high_since=now)
    state = demand_correction_step(state, 100, now+timedelta(minutes=10), active=False)
    assert state.high_since == now
    state = demand_correction_step(state, 100, now+timedelta(minutes=21), active=True)
    assert state.correction == 2
    print('Heating sustain timer includes inactive interval')

async def test_sticky_hold_ignores_cylinder_temperature():
    target, _, _ = dhw_target(60, None, False, 0, DhwCyclingState(holding=True), dt_util.utcnow())
    assert target == 55
    print('Cylinder 60 C, sticky-hold flow target 55 C')

async def test_partial_zone_loss_can_infer_dhw():
    assert infer_dhw_demand(False, True, 100, zone_max_demand([0, None]))
    print('One missing zone + one zero zone + aggregate 100 is inferred as DHW')

async def test_stale_return_retains_penalty():
    state = return_ceiling_step(ReturnCorrectionState(-20), None, False)
    assert state.correction == -20
    print('Stale return sensor retains -20 K correction')
