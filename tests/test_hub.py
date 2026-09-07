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


def test_ignition_counter_counts_sub_minute_events():
    # change 3: event-driven, so ignitions closer together than the 60 s poll
    # interval (6 starts in 5 min observed in the field) are all counted.
    hub = BoilerFlowHub()
    now = T0
    for _ in range(6):
        now = now + timedelta(seconds=10)
        count = hub.record_ignition(now)
    assert count == 6


def test_ignition_counter_prunes_outside_window():
    hub = BoilerFlowHub()
    now = T0
    hub.record_ignition(now)  # ignition 1
    now = now + timedelta(minutes=1)
    hub.record_ignition(now)  # ignition 2
    now = now + timedelta(minutes=15)  # well outside the 10-minute window
    count = hub.record_ignition(now)  # ignition 3, but 1 & 2 have aged out
    assert count == 1


def test_cycles_10min_reads_current_window_without_adding():
    hub = BoilerFlowHub()
    now = T0
    hub.record_ignition(now)
    assert hub.cycles_10min(now + timedelta(minutes=1)) == 1
    assert hub.cycles_10min(now + timedelta(minutes=11)) == 0


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
    hub.record_write(52.5, T0, target_changed=True)
    m = hub.write_memory()
    assert m.last_written_setpoint == 52.5 and m.last_written_at == T0 and m.last_target_change == T0


def test_write_memory_re_assert_advances_last_written_at_only():
    hub = BoilerFlowHub()
    hub.record_write(52.5, T0, target_changed=True)
    later = T0 + timedelta(minutes=1)
    hub.record_write(52.5, later, target_changed=False)
    m = hub.write_memory()
    assert m.last_written_setpoint == 52.5
    assert m.last_written_at == later  # advances every re-assertion
    assert m.last_target_change == T0  # target itself has not changed
