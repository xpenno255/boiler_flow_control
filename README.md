<p align="center"><img src="custom_components/boiler_flow_control/brand/icon@2x.png" width="160" alt="Boiler Flow Control icon"></p>

# Boiler Flow Control

A Home Assistant integration that supervises an EMS-ESP boiler's **flow-temperature setpoint**. It combines weather compensation with demand or optional room feedback, while handling stored hot water separately. Evohome and the boiler retain control of their relays, pump and burner.

## Upgrade to 0.3.0

Install **0.3.0** through HACS and restart Home Assistant. Existing entity IDs, weather-curve settings and mode selection are retained. Requires Home Assistant **2026.3 or newer**; tested on 2026.9.0.

- Automatic cycling temperature reductions and the permanent 55°C DHW hold have been removed. An old cycling hold is cleared automatically during upgrade.
- DHW has a configurable **cylinder target**, default **60°C**. Check this matches your cylinder controller. You can select its live target entity to follow schedule/hygiene target changes.
- **DHW fallback flow** defaults to your existing DHW flow ceiling (normally 70°C). Confirm it is appropriate for your boiler and cylinder. The integration never increases the boiler's maximum setting.
- Existing `dhw_return_ceiling` settings are retired and ignored. A high return alone does not justify reducing cylinder heat transfer.
- The existing reset button retains its unique ID; its new display name is **Reset DHW diagnostics**.
- Room feedback is optional. The original weather curve remains the starting point.

New installations start in **shadow** mode. An upgrade preserves the restored auto/shadow/hold selection.

## Behaviour

**Space heating:** the original radiator-exponent weather curve (55°C at −3°C outdoors, by default), bounded by your heating floor/ceiling. Without room inputs, sustained zone demand adjusts the curve by up to ±8 K. With configured room thermostats, slow room recovery can add up to 8 K instead. Return temperature provides a small efficiency trim only after five minutes of heating with circulation evidence: filtered input, a ±1 K deadband, 0.2 K/minute and a maximum −6 K trim. Cold-room or high-demand pressure suppresses the negative trim; stale return data removes it.

**Stored hot water:** normally follows cylinder temperature plus the DHW delta, with at least 5 K requested headroom above the cylinder target and the configured DHW floor/ceiling. Missing cylinder readings use the DHW fallback, never the weather curve. Both entering and leaving DHW bypass the heating hold. Missing readings, inadequate progress (less than 1 K over 30 minutes by default), a charge exceeding 120 minutes, or insufficient flow headroom produce diagnostics. Poor progress/timeout uses the fallback until the charge ends or diagnostics are reset. These are supervisory indications; draw-off and sensor position can affect apparent progress.

**Cycling:** counts exact off→on events and records the last observed burn duration. An optional appliance-relay input helps distinguish a requested stop from a possible temperature-limit stop. Frequent starts are **diagnostic only**. A count alone cannot establish whether flow should rise or fall. Validate the selected heating-active signal against flame state or the boiler's burner-start counter on your installation.

**Inputs and mode detection:** configured zones replace the aggregate heating demand because the aggregate may include DHW. Inferring DHW requires every configured zone to be fresh and zero, aggregate demand ≥90%, and two minutes of sustained evidence. A positive HW relay signal is immediate. Brief missing evidence has a two-minute grace period; a confirmed relay-off with aggregate below 90 ends DHW immediately. Demand/cylinder readings expire after 30 minutes by default, outdoor readings after 120, and return readings after 10. Static target and maximum-flow settings do not expire merely because they are unchanged.

**Writes:** auto reasserts the effective target every minute because this installation's EMS setpoint otherwise reverts to the front-panel setting. Target changes normally have a 10-minute hold and 1 K hysteresis. Limits and number-entity step are resolved before writing and recording the value. Delayed readback is reported separately from service success. A configured maximum-flow entity becoming unavailable, or contradictory entity/configuration limits, suspends writes. Existing boiler hardware limits remain in force.

**Shadow:** uses the same limits and target arbitration with separate virtual memory; no boiler writes. It models decisions, not the boiler's hypothetical thermal response. Hold disables writes. Manual changes after a confirmed write trigger the configured manual-hold interval; a return to the known dial setting is treated as the boiler's normal fallback.

## Setup and entities

Add through **Settings → Devices & Services → Add Integration → Boiler Flow Control**. Configure the flow-setpoint number and outdoor sensor, then the optional inputs. Edit these later through the integration's options.

Typical entities in this installation:

| Input | Example |
|---|---|
| Flow setpoint | `number.boiler_selflowtemp` |
| Outdoor | `sensor.met_office_weoley_castle_temperature` |
| Current flow | `sensor.boiler_curflowtemp` |
| Return | `sensor.boiler_return_temp_temperature` |
| Burner/heating active | `binary_sensor.boiler_heatingactive` |
| Burner power | `sensor.boiler_curburnpow` |
| Aggregate demand | `sensor.01_144444_heat_demand` |
| HW relay demand | `sensor.13_163605_relay_demand` |
| Cylinder temperature | `sensor.07_045877_temperature` |
| Boiler maximum | `number.boiler_heatingtemp` |

Disable the existing automation that writes the same flow setpoint before using auto, so there is one controller for that number.

Diagnostics include Mode, Flow Setpoint, Return Temperature Used, Cycles (10 min), Cycling Status, Last Burn Duration, DHW Status, Heat Demand Filtered and Last Write. Flow Setpoint attributes separate **requested**, **effective/would-write**, **sent** and **confirmed** targets. A confirmed target is the most recent matching setpoint readback, not proof of actual water temperature.

The new **DHW Active** binary sensor (normally `binary_sensor.boiler_flow_control_dhw_active`) shares the resolved DHW signal. Select it as the DHW gate in the companion `ot_thermostat_control` integration if that currently relies on the unreliable raw relay. It is on during DHW-only and mixed operation; this release does not change the companion integration automatically.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests scripts
.venv/bin/ruff format --check custom_components tests scripts
.venv/bin/python scripts/build_release.py
```

The archive contains only the integration files, including its local brand images. The original editable icon is in `assets/icon.svg`; regenerate the two PNG sizes with `scripts/build_icon.py` after installing CairoSVG.

See [the current specification](docs/spec.md), [release notes](CHANGELOG.md), and [the pre-change review](docs/review_20260913.md). Lower gas use must be established through comparable measurements of gas, comfort and hot-water service; fewer starts alone do not prove a saving.
