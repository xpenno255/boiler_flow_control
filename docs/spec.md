# Boiler Flow Control — base specification

Status: v0.2, 2026-09-07. Domain `boiler_flow_control`, HACS layout like `ot_thermostat_control`.
See §10 for the v0.2 field findings and design changes on top of the v0.1 base spec below.

## 1. Purpose

Set the boiler's flow-temperature setpoint dynamically so that it runs long, low-modulation burns
instead of short cycles, condenses as much as possible, and still meets heating and hot-water demand.
Two regimes with different physics and different targets:

- **Space heating**: the lowest flow temperature that satisfies the evohome zones' demand, i.e.
  weather compensation corrected by measured demand and by return temperature.
- **Hot water (stored cylinder)**: a flow temperature matched to what the cylinder coil can actually
  absorb, so the boiler does not hit its setpoint and stop within a minute of starting.

Observed on 2026-09-05 04:39–04:45 BST: `binary_sensor.boiler_heatingactive` toggled six times in
six minutes during a DHW-only call while the owner's automation had raised flow to 70 °C. Owner's
diagnosis: the cylinder coil returns water too warm for the boiler to keep burning at that flow.

## 2. System as it is

| Thing | Entity / fact |
|---|---|
| Boiler interface | ems-esp. Flow setpoint `number.boiler_selflowtemp` (50 in heating, owner's automation ramps to 70 on DHW). Max `number.boiler_heatingtemp` 70. Current flow `sensor.boiler_curflowtemp`. Burner power `sensor.boiler_curburnpow`, limits `number.boiler_burnminpower` 0 %, `number.boiler_burnmaxpower` 60 %, anti-cycle `number.boiler_burnminperiod` 3 min. Pump `sensor.boiler_heatingpumpmod`, `select.boiler_pumpmode` propo.low. Flags `binary_sensor.boiler_heatingactive`, `boiler_dhw_active`, `boiler_dhw_charging`, `boiler_dhw_3wayvalve`, `boiler_tapwateractive` (the dhw flags did NOT fire for the stored cylinder). |
| Return temperature | Boiler does not report it. Strap-on BLE sensors exist: `sensor.boiler_flow_temperature_temperature`, `sensor.boiler_return_temp_temperature` — both **unavailable** on 2026-09-05; need batteries/re-pairing. |
| Zone control | evohome controller `01:144444` via ramses_cc. Boiler relay `13:207292` (appliance control), heating valve `13:237610`, hot-water valve `13:163605`. Demands: `sensor.01_144444_heat_demand` (aggregate %), `sensor.13_163605_relay_demand` (100 while the cylinder is being heated), `sensor.01_144444_hw_relay_demand`, per-zone `sensor.01_144444_0X_heat_demand`. Cylinder sensor `sensor.07_045877_temperature`. Relays are on/off; the boiler is not on OpenTherm, so flow temperature is entirely ems-esp's to set. |
| Outdoor temperature | `sensor.met_office_weoley_castle_temperature` (dry bulb); fallback `weather.home`. |
| Comfort side | `ot_thermostat_control` v2 reads `number.boiler_selflowtemp` live (DHW-gated on `sensor.13_163605_relay_demand`) for radiator derating. It never sets flow. |
| Emitters | Radiators sized for reduced flow (living room 2 × K3). Installed ΔT50 output per room is in `ot_thermostat_control/house/rooms/*.yaml`; at 50 °C flow output is ~41 % of ΔT50. |

## 3. Behaviour

### 3.1 Modes, decided every cycle (1 min)
| Mode | Condition | Flow setpoint |
|---|---|---|
| `idle` | no heating demand, no DHW demand | park at the heating curve value, **re-asserted every cycle in auto** (§10) |
| `heating` | heating demand signal > 0 (§10: zone max, or aggregate if no zones configured), DHW demand = 0 | heating curve + demand correction, bounded by return ceiling and floor; **written every cycle in auto** (§10) |
| `dhw` | `13:163605` relay demand > 0, **or inferred** (§10: zone list configured, aggregate ≥ 90, zone max = 0) | DHW target (§3.3); **written every cycle in auto** (§10) |
| `dhw_and_heating` | both, **relay signal only** — inference cannot separate this from plain high heating demand (§10) | DHW target (cylinder wins; heating continues on the same water); **written every cycle in auto** (§10) |
| `manual_hold` | `selflowtemp` differs from what we last wrote **and** from the current dial value (max-flow entity) (§10) | hold for N min, then resume |
| `off` | integration disabled | write nothing |

### 3.2 Heating flow temperature
1. **Curve**: `T_flow = T_room_design + (T_design_flow − T_room_design) · ((T_room_design − T_out) / (T_room_design − T_out_design))^(1/n)`, radiator exponent n = 1.3. Defaults: design outdoor −3 °C, design flow 55 °C, room 20 °C. Clamped to [`flow_min` 35, `flow_max` 65].
2. **Demand correction**: heat demand signal, low-pass filtered (10 min). §10: this is the max of the configured zone demand sensors (ignoring unavailable ones), not the aggregate controller sensor, because the aggregate includes stored-hot-water demand and would otherwise read e.g. 100 through a DHW-only charge; falls back to the aggregate sensor only when no zone list is configured. Above 70 % for 20 min → +2 K per 10 min up to +8 K. Below 30 % for 20 min → −2 K per 10 min down to −8 K. Resets towards 0 when demand sits between.
3. **Return ceiling**: if return temperature > `return_ceiling` (default 50 °C) → −2 K per cycle until below. Only when the return sensor is available and fresh (< 10 min).
4. **Cycling guard**: if `heatingactive` has ignited ≥ 3 times in 10 min and demand < 50 % → −3 K (the boiler cannot modulate low enough at this flow). If demand is high and cycling → do nothing here; the fix is elsewhere (pump, min power). §10: the ignition count is event-driven (each off→on transition timestamped as it happens), not read from the 60 s poll, because the boiler can short-cycle faster than once a minute.
5. **Floor**: never below the value needed for the most demanding zone: from the OT survey's installed outputs and the zone's demand, or simply `flow_min`. Phase 1 uses `flow_min`.
6. **Hysteresis and hold (amended, §10)**: the *target* value only changes when it differs by ≥ 1 K from the current target, and at most once per `min_hold` (default 10 min), except for the return ceiling and leaving DHW mode, which may act each cycle. This no longer gates whether a write happens — see §10: in auto mode the target is written (re-asserted) every cycle regardless, because the boiler decays an un-rewritten setpoint back to the dial value within ~2 min.

### 3.3 DHW flow temperature
Goal: heat the cylinder to its target without the boiler overshooting its own setpoint and stopping.
1. Target flow = `cylinder_temp + dhw_delta` (default 20 K), clamped to [`dhw_flow_min` 55, `dhw_flow_max` 70]. As the cylinder warms the flow rises with it, so the coil ΔT stays roughly constant instead of collapsing at the end of the charge.
2. Return ceiling for DHW `dhw_return_ceiling` (default 60 °C): if return exceeds it, lower flow 3 K; the coil is saturated.
3. Cycling guard: ≥ 3 toggles in 10 min → lower flow 5 K and log; if that fails twice, hold at `dhw_flow_min` and raise a repair issue: the coil/pump/min-power need attention, software cannot fix it.
4. On leaving DHW mode restore the heating value immediately (do not let 70 °C linger into the heating cycle, which OT v2 had to guard against).

### 3.4 Safety and interplay
- Never exceed `number.boiler_heatingtemp`.
- If ems-esp is unavailable, write nothing and expose `state = no_boiler`.
- Owner's existing "ramp to 70 on DHW" automation must be disabled when this integration goes active; otherwise they fight. Coordination item.
- OT v2 keeps reading `selflowtemp` gated on the HW relay; nothing to change there, but a lower heating flow reduces radiator output, and the Studio (single K1, corner room) is the first to run out. Watch its `state`/`would_write` when lowering the curve.
- §10: in auto mode, `number.set_value` is called every cycle (60 s) while the mode is `heating`/`dhw`/`dhw_and_heating`/`idle` (park value), not just when the target changes — ems-esp reverts `selflowtemp` to the dial value (`number.boiler_heatingtemp`, the front-panel setting) by itself within ~2 min of nothing rewriting it.

## 4. Entities
Hub-style single config entry.
- `sensor.bfc_mode`, `sensor.bfc_flow_setpoint` (with attributes: curve, demand_correction, return_correction, cycling_correction, reason), `sensor.bfc_return_temperature_used`, `sensor.bfc_cycles_10min`, `sensor.bfc_heat_demand_filtered`, `sensor.bfc_last_write`.
- `switch.bfc_enabled`, `select.bfc_mode_override` (auto / shadow / hold), `number.bfc_design_flow`, `number.bfc_design_outdoor`, `number.bfc_return_ceiling`, `number.bfc_dhw_delta`.
- Shadow mode first, exactly as OT v2: compute and expose `would_write`, write nothing until switched.

## 5. Configuration
Entities for: flow setpoint number, current flow, return temperature, heating-active flag, burner power, aggregate heat demand, HW relay demand, cylinder temperature, outdoor temperature. §10: optionally, a list of per-zone heat demand sensors (`zone_demand_entities`) — when configured, this replaces the aggregate sensor as the heating-demand signal and enables DHW inference. Numbers: curve parameters, clamps, ceilings, DHW delta, hold times. Everything optional except the flow setpoint number and outdoor temperature; each missing input disables the feature that needs it and is listed on `bfc_mode`.

## 6. Code layout (mirror OT v2)
```
custom_components/boiler_flow_control/
  core/curve.py     pure: heating curve, corrections, DHW target, hysteresis    (tests)
  core/policy.py    pure: mode decision, write-or-not, manual hold              (tests)
  hub.py            filtered demand, cycle counter, return freshness, store
  coordinator.py    HA glue: read entities, run core, one number.set_value
  config_flow.py, sensor.py, switch.py, select.py, number.py, diagnostics.py
tests/              pytest under a HA venv (pytest<9, pytest-homeassistant-custom-component)
```

## 7. Before building: data to collect (two cold weeks)
Log at 1 min: `selflowtemp`, `curflowtemp`, return (once the BLE sensor is back), `curburnpow`,
`heatingactive`, `01_144444_heat_demand`, `13_163605_relay_demand`, `07_045877_temperature`,
outdoor. Questions the data must answer: how often does the boiler cycle in heating at 50 °C and at
what demand; what return temperature does the cylinder produce through a charge; how long is a DHW
charge; does the boiler ever fail to reach 50 °C flow at high demand (curve too low).

## 8. Expected benefit (to be confirmed by §7)
Weather compensation from a fixed 50 °C is worth a few percent of gas, mostly on mild days, plus a
large reduction in burner starts (`sensor.boiler_burnstarts` is the counter to watch). The DHW change
is about stopping 6-starts-in-6-minutes; the gas saving there is small, the wear saving is not.

## 9. Open questions for the owner
- Boiler make/model and its minimum modulation (kW). Decides whether DHW cycling can be fixed by flow temperature at all.
- Cylinder size and coil rating; cylinder stat setpoint (evohome DHW target) and differential.
- Whether `pumpmode` propo.low is deliberate. Pump speed strongly affects ΔT and return temperature.
- Is the existing DHW ramp automation happy to be retired in favour of this?

## 10. v0.2 field findings (2026-09-07)

Three defects surfaced from live house data, addressed as follows.

**1. The aggregate demand sensor includes DHW; the HW relay sensor misses charges.**
`sensor.01_144444_heat_demand` reads 100 during a DHW-only cylinder charge while every
per-zone demand sensor (`sensor.01_144444_0X_heat_demand`) reads 0 — it is not a pure
heating-demand signal. Separately, the HW relay sensor (`13:163605`) is unreliable: RF
reception misses it for some charges, so it cannot be the sole DHW signal.
- Design response: a new optional `zone_demand_entities` list (multi-select, sensor domain).
  When configured, the heating-demand signal (feeding the low-pass filter, demand
  correction, and heating-mode detection) is the max of the configured zones' numeric
  states, ignoring unknown/unavailable ones; it falls back to the aggregate sensor only
  when no zone list is configured. DHW detection becomes: HW relay demand > 0, **or**
  (zone list configured AND aggregate demand ≥ 90 AND zone-max demand == 0). This lets a
  DHW-only charge be recognised even when the relay sensor misses it, and stops it
  polluting the heating-side demand correction (heating demand reads 0 during a DHW-only
  charge instead of appearing to be near-100% heating load).
  Limitation: `dhw_and_heating` still requires the relay signal — the inference cannot
  distinguish it from plain high heating demand, because a genuine mixed charge and a
  missed-relay DHW-only charge look identical from the aggregate alone once any zone has
  demand > 0 (which also means the inference condition `zone_max == 0` no longer holds, so
  it correctly does not fire). See `core/policy.infer_dhw_demand`.

**2. ems-esp decays a written flow setpoint back to the dial value.**
If nothing rewrites `number.boiler_selflowtemp` for ~2 minutes, the boiler reverts it by
itself to the front-panel dial value (70 °C in the owner's install, which equals the
configured max-flow entity `number.boiler_heatingtemp`). The owner's current "ramp to 70 on
DHW" automation works around this by rewriting every minute; BFC in auto mode must take
over that duty for every mode it drives.
- Design response (write-once → re-assert semantics): hysteresis and `min_hold_minutes`
  now govern only when the **target value** may change, not whether a write happens. In
  auto mode, `number.set_value` is called every cycle (60 s) while the mode is
  `heating`/`dhw`/`dhw_and_heating`, and also when idle (parked at the curve value). The
  immediate-target-change exemptions (return ceiling, leaving DHW) are unchanged.
  `sensor.bfc_last_write` now advances every cycle in auto; a new attribute
  `last_target_change` on that sensor records when the value itself last changed.
  Manual-hold detection is revert-aware: a live `selflowtemp` that differs from what we
  last wrote is only a manual change if it *also* differs from the current dial value
  (the max-flow entity). A revert-to-dial is boiler behaviour, not a manual hold. A
  genuine hand-turn to exactly the dial value is therefore indistinguishable from a
  revert and is deliberately ignored — the enable switch / override select is the escape
  hatch for that edge case. Shadow mode still writes nothing.

**3. The boiler short-cycles faster than the 60 s poll can count.**
Six starts in five minutes were observed on `binary_sensor.boiler_heatingactive` while the
polled 60 s cycle counter recorded only three — sub-minute toggles were undercounted.
- Design response: the coordinator subscribes to state changes of the heating-active
  binary sensor via `homeassistant.helpers.event.async_track_state_change_event`
  (unsubscribed on unload). Each off→on transition is timestamped into the hub's rolling
  10-minute window as it happens, independent of the 60 s poll. The poll only reads the
  current window size for the sensor entity; it no longer feeds the counter. See
  `hub.record_ignition` / `hub.cycles_10min` and `coordinator.async_subscribe_heating_active`.
