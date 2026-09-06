# Boiler Flow Control

Phase 1 of a Home Assistant custom integration that sets the boiler's flow-temperature
setpoint dynamically (weather compensation + demand/return corrections for space heating,
a cylinder-matched target for DHW) so ems-esp runs long, low-modulation, condensing burns
instead of short cycles. Full behavioural spec: `docs/spec.md`.

## What it does

- **Heating**: weather-compensation curve (design flow 55 °C at design outdoor −3 °C),
  corrected by low-pass-filtered aggregate heat demand, a return-temperature ceiling, and a
  cycling guard, clamped to `flow_min`/`flow_max`.
- **DHW**: target flow = cylinder temperature + `dhw_delta`, clamped to
  `dhw_flow_min`/`dhw_flow_max`, with its own return ceiling and cycling guard. If the
  cycling guard fails twice it holds at `dhw_flow_min` and raises a repair issue — the
  coil/pump/minimum burner power need attention, software cannot fix it.
- Detects a manual change to the flow-setpoint entity and holds off for `manual_hold_minutes`.
- Writes at most once per cycle (60 s), gated by hysteresis and `min_hold_minutes`, except
  the return ceiling and leaving DHW mode, which may act every cycle.
- Never exceeds the configured max-flow number.

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
  `sensor.bfc_last_write`.
- `switch.bfc_enabled`, `select.bfc_mode_override` (auto / shadow / hold).
- `number.bfc_design_flow`, `number.bfc_design_outdoor`, `number.bfc_return_ceiling`, `number.bfc_dhw_delta`.

## Configuration

Set up via **Settings → Devices & Services → Add Integration → Boiler Flow Control**.
Required: the flow-setpoint number and an outdoor-temperature sensor. Everything else
(current flow, return temperature, heating-active flag, burner power, aggregate heat
demand, HW relay demand, cylinder temperature, max-flow number) is optional; each missing
input disables the feature that needs it and is listed on `sensor.bfc_mode`.

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
