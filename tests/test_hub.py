"""Tests for hub.py: demand low-pass filter, toggle counter, return freshness, write memory."""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.boiler_flow_control.hub import BoilerFlowHub

T0 = datetime(2026, 1, 15, 7, 0, tzinfo=timezone.utc)


def test_demand_filter_none_returns_current_value():
    hub = BoilerFlowHub()
    assert hub.sample_demand(None, T0) is None


def test_demand_filter_seeds_then_smooths():
    hub = BoilerFlowHub()
    assert hub.sample_demand(50.0, T0) == pytest.approx(50.0)
    # 10 minutes later, tau=10min -> alpha=0.5
    value = hub.sample_demand(100.0, T0 + timedelta(minutes=10))
    assert value == pytest.approx(75.0)


def test_demand_filter_holds_value_when_input_drops_out():
    hub = BoilerFlowHub()
    hub.sample_demand(50.0, T0)
    assert hub.sample_demand(None, T0 + timedelta(minutes=5)) == pytest.approx(50.0)


def test_toggle_counter_counts_state_changes_only():
    hub = BoilerFlowHub()
    now = T0
    assert hub.sample_heating_active(False, now) == 0
    for i in range(6):
        now = now + timedelta(minutes=1)
        state = i % 2 == 0  # alternate every cycle -> a toggle each time
        count = hub.sample_heating_active(state, now)
    assert count == 6  # six toggles inside a 10-minute window


def test_toggle_counter_prunes_outside_window():
    hub = BoilerFlowHub()
    now = T0
    hub.sample_heating_active(False, now)
    now = now + timedelta(minutes=1)
    hub.sample_heating_active(True, now)  # toggle 1
    now = now + timedelta(minutes=1)
    hub.sample_heating_active(False, now)  # toggle 2
    now = now + timedelta(minutes=15)  # well outside the 10-minute window
    count = hub.sample_heating_active(True, now)  # toggle 3, but 1 & 2 have aged out
    assert count == 1


def test_toggle_counter_ignores_missing_data():
    hub = BoilerFlowHub()
    assert hub.sample_heating_active(None, T0) == 0


def test_return_freshness():
    hub = BoilerFlowHub()
    value, fresh = hub.sample_return(55.0, T0)
    assert value == 55.0 and fresh
    # stale sample: no new reading for 11 minutes, but the last value is still reported
    value, fresh = hub.sample_return(None, T0 + timedelta(minutes=11))
    assert value == 55.0 and not fresh
    # fresh again once a new reading arrives
    value, fresh = hub.sample_return(60.0, T0 + timedelta(minutes=11))
    assert value == 60.0 and fresh


def test_write_memory_round_trip():
    hub = BoilerFlowHub()
    assert hub.write_memory().last_written_setpoint is None
    hub.record_write(52.5, T0)
    m = hub.write_memory()
    assert m.last_written_setpoint == 52.5 and m.last_written_at == T0
