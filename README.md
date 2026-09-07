# Boiler Flow Control

Phase 1 of a Home Assistant custom integration that sets the boiler's flow-temperature
setpoint dynamically (weather compensation + demand/return corrections for space heating,
a cylinder-matched target for DHW) so ems-esp runs long, low-modulation, condensing burns
instead of short cycles. Full behavioural spec: `docs/spec.md`.

## What it does

- **Heating**: weather-compensation curve (design flow 55 °C at design outdoor −3 °C),
  corrected by a low-pass-filtered heat-demand signal, a return-temperature ceiling, and a
  cycling guard, clamped to `flow_min`/`flow_max`. The demand signal is the max of the
  configured per-zone demand sensors (`zone_demand_entities`), or the aggregate controller
  sensor if no zone list is configured — the aggregate includes stored-hot-water demand and
  would otherwise read high through a DHW-only charge.
- **DHW**: target flow = cylinder temperature + `dhw_delta`, clamped to
  `dhw_flow_min`/`dhw_flow_max`, with its own return ceiling and cycling guard. DHW is
  detected from the HW relay demand, or inferred (when a zone list is configured) from the
  aggregate-includes-DHW signature: aggregate ≥ 90 while every zone reads 0 — the relay
  sensor misses some charges over RF. `dhw_and_heating` still requires the relay signal;
  the inference cannot separate it from plain high heating demand. If the cycling guard
  fails twice it holds at `dhw_flow_min` and raises a repair issue — the coil/pump/minimum
  burner power need attention, software cannot fix it.
- Detects a manual change to the flow-setpoint entity and holds off for `manual_hold_minutes`.
  A live value that reverts to the current max-flow (dial) value is never treated as manual
  — the boiler decays an un-rewritten setpoint back to the dial by itself.
- In auto mode, writes `number.set_value` **every cycle** (60 s) while the mode is
  `heating`/`dhw`/`dhw_and_heating`, and when idle (parked at the curve value) — the boiler
  reverts the setpoint to the dial value within ~2 min if nothing rewrites it. Hysteresis
  and `min_hold_minutes` govern only when the *target* may change (except the return
  ceiling and leaving DHW mode, which may change it every cycle); shadow mode still writes
  nothing.
- Never exceeds the configured max-flow number.
- Counts boiler ignitions (off→on transitions of the heating-active sensor) event-driven,
  not from the 60 s poll, so it does not undercount short-cycling faster than once a minute.

## Shadow-first rollout

`select.bfc_mode_override` defaults to **shadow**: every cycle computes and exposes what it
*would* write (`sensor.bfc_flow_setpoint.would_write`), but nothing is sent to the boiler.
Watch it for a while, then switch to **auto** to let it write, or **hold** to freeze
writes without disabling the integration.

## Entities

- `sensor.bfc_mode` — `idle` / `heating` / `dhw` / `dhw_and_heating` / `manual_hold` / `off` /
  `no_boiler`, with `reason`, `disabled_features` and manual-hold/DHW-issue flags as attributes.
- `sensor.bfc_flow_setpoint` — the value written or that would be written; attributes: `curve`,
  `demand_correction`, `return_correction`, `cycling_correction`, `reason`, `would_write`.
- `sensor.bfc_return_temperature_used`, `sensor.bfc_cycles_10min`, `sensor.bfc_heat_demand_filtered`,
  `sensor.bfc_last_write` (attribute `last_target_change`: when the target value itself last changed,
  as distinct from `last_write`, which advances every re-assertion in auto mode).
- `switch.bfc_enabled`, `select.bfc_mode_override` (auto / shadow / hold).
- `number.bfc_design_flow`, `number.bfc_design_outdoor`, `number.bfc_return_ceiling`, `number.bfc_dhw_delta`.

## Configuration

Set up via **Settings → Devices & Services → Add Integration → Boiler Flow Control**.
Required: the flow-setpoint number and an outdoor-temperature sensor. Everything else
(current flow, return temperature, heating-active flag, burner power, aggregate heat
demand, HW relay demand, cylinder temperature, max-flow number, zone demand sensors) is
optional; each missing input disables the feature that needs it and is listed on
`sensor.bfc_mode`.

`zone_demand_entities` (a multi-entity selector, sensor domain) lets you list the
per-zone heat-demand sensors (e.g. `sensor.01_144444_0X_heat_demand`). When set, it
replaces the aggregate sensor as the heating-demand signal and enables DHW-only-charge
inference for houses where the HW relay sensor misses charges over RF.

The owner's real entity ids (see `docs/spec.md` §2), for reference when configuring:

| Input | Entity |
|---|---|
| Flow setpoint | `number.boiler_selflowtemp` |
| Outdoor temperature | `sensor.met_office_weoley_castle_temperature` |
| Current flow | `sensor.boiler_curflowtemp` |
| Return temperature | `sensor.boiler_return_temp_temperature` |
| Heating active | `binary_sensor.boiler_heatingactive` |
| Burner power | `sensor.boiler_curburnpow` |
| Aggregate heat demand | `sensor.01_144444_heat_demand` |
| HW relay demand | `sensor.13_163605_relay_demand` |
| Cylinder temperature | `sensor.07_045877_temperature` |
| Max flow | `number.boiler_heatingtemp` |

The remaining tunables (`flow_min`, `flow_max`, `dhw_flow_min`, `dhw_flow_max`,
`dhw_return_ceiling`, `min_hold_minutes`, `manual_hold_minutes`) live in the options flow.

**Before switching to auto**, disable the owner's existing "ramp to 70 °C on DHW"
automation — otherwise the two fight over the same flow setpoint (§3.4).

## Development

```
pip install -r requirements-test.txt  # or use the ot_thermostat_control venv
pytest
python -m compileall custom_components
```
