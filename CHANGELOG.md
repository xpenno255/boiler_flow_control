# Changelog

## 0.3.0 — 2026-09-13

Improves hot-water completion and makes flow control respond to measured operating conditions.

- Remove automatic cycling temperature reductions and the permanent DHW low-temperature hold; clear legacy holds on upgrade. Cycling now provides diagnostics without assuming the direction of a temperature adjustment.
- Add configurable cylinder target/live target input, DHW fallback, progress and timeout monitoring. Missing cylinder data no longer uses the weather curve. Preserve requested completion headroom within existing boiler limits.
- Apply both DHW transitions immediately and retry failed transitions without consuming the hold exemption.
- Resolve limits and supported number steps before writing, reporting and recording targets. Distinguish service success, pending readback and confirmed output; avoid false manual holds after capping.
- Give shadow mode separate control/write memory and the same target arbitration as auto.
- Replace rapid return-temperature reduction with a filtered, bounded trim using elapsed time, settling, a deadband and comfort constraints. Remove stale penalties.
- Require complete fresh zone data and debounce for inferred DHW. Add a shared DHW-active binary sensor for companion integrations.
- Add optional room recovery feedback and cycling telemetry: last observed burn duration, possible stop cause, burner power, flow and return temperatures, and starts per observed DHW charge.
- Preserve enable/override/tunables across restarts even when the boiler is unavailable. Reset inactive demand sustain timers and retire obsolete options.
- Ship an original boiler/circulation icon, HACS release archive, reproducible build and CI tests.

After upgrading through HACS, restart Home Assistant. Check the new cylinder target (default 60°C) and fallback (your existing DHW maximum, normally 70°C) in options. Room feedback and appliance-relay diagnostics are optional. Select the new DHW Active binary sensor in the companion OT integration if you want it to use the same resolved signal. The companion integration and live boiler configuration are not changed by this release.

Gas savings and cycling improvements remain subject to field measurement; the release does not tune boiler minimum power, pump settings or hardware limits.

## 0.2.1

Correct write timing, persistence, DHW cycling state, optional configuration removal and event-driven ignition handling.

## 0.2.0

Add zone-demand heating input, inferred DHW detection, EMS setpoint reassertion and event-driven ignition counting.
