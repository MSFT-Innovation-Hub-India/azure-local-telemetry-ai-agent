# SOP-PMP-001: Pump skid operating envelope and observation

| Document control | Value |
|---|---|
| Revision / effective date | 1.0 / 2026-11-13 |
| Facility / equipment family | Fictional Northbank Demonstration Works / NB-CP centrifugal pump skid |
| Applicable assets | PUMP-001, PUMP-002, PUMP-003 |
| Document owner | Demonstration reliability engineering |
| Status | SYNTHETIC TRAINING DOCUMENT - NOT APPROVED FOR REAL EQUIPMENT |

## PURPOSE

This fictional procedure describes interpretation of an already-running water
circulation skid. Values are invented for the simulator and are not manufacturer
limits. The skid contains a motor, drive-end bearing, lubrication circuit and
centrifugal pump. Asset IDs identify complete skids; each measurement identifies
the relevant component. No agent or demo screen is authorized to operate equipment.
Actual maintenance and intervention require qualified personnel and approved
site-specific procedures.

## ENVELOPE

Use the following envelope only for steady, running simulated equipment.

| Parameter / database field | Typical running range | Interpretation |
|---|---|---|
| Speed / speed_rpm | 1475-1485 rpm | Compare with current and delivered flow before assuming mechanical overload |
| Motor current / motor_current_a | 17-20 A | A rise with bearing heat can support friction; a fall with low flow can support unloading |
| Motor temperature / motor_temperature_c | 58-70 C | Check ambient conditions and current; heat alone is not a diagnosis |
| Bearing temperature / bearing_temperature_c | 55-65 C | Investigate sustained rise using vibration and lubricant pressure |
| Overall vibration / vibration_mm_s | 1.5-2.2 mm/s RMS | This is an invented overall indicator, not a frequency-spectrum diagnosis |
| Suction pressure / suction_pressure_bar | 1.3-1.7 bar | Pressure is gauge pressure; the demo does not calculate NPSH |
| Discharge pressure / discharge_pressure_bar | 5.5-6.1 bar | Compare with suction pressure, flow and speed |
| Flow / flow_m3_h | 40-44 m3/h | Compare with current, pressure and operating state |
| Lubricant pressure / lubricant_pressure_bar | 2.2-2.6 bar | A drop alongside bearing heat/vibration strengthens a lubrication concern |
| Ambient / ambient_temperature_c | 24-30 C | Compare motor/bearing temperature changes against ambient |

Normal variation inside these ranges should not generate an alert. An isolated
excursion does not satisfy a sustained-window rule.

## OBSERVATION

Confirm asset identity, units, running state and timestamp before interpreting
values. Compare at least a 60-second trend, not just the latest point. Compare the
healthy reference PUMP-003 when available, but do not assume two real pumps have
identical duty. The simulator's scenario labels are testing metadata and must
not be used as evidence by the diagnostic agent.

## DATA-QUALITY

Samples normally arrive approximately every two seconds. A gap greater than six
seconds invalidates a continuous sustained-window assessment. If the newest
sample is more than 15 seconds old, open a telemetry-stale alert. Do not treat
missing data as normal operation, and do not clear a mechanical alert merely
because readings stopped.

Future timestamps, non-good quality or non-running state must not be interpreted
using this running envelope. Verify clocks, source identity, sensor quality,
communications and database ingestion before asserting equipment recovery.
Close a telemetry-stale alert only after 20 seconds of fresh, continuous readings.

## ESCALATION

The rules create advisory demonstration alerts, not trips. Preserve evidence and
contact the responsible operator for a sustained abnormal pattern. Any response
on real equipment must follow the actual approved operating procedure and site
safety arrangements. Never infer permission to bypass a protection or continue
running from an AI-generated explanation.
