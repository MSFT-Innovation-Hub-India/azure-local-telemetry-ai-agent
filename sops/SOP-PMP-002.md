# SOP-PMP-002: Correlated telemetry troubleshooting

| Document control | Value |
|---|---|
| Revision / effective date | 1.0 / 2026-11-13 |
| Facility / equipment family | Fictional Northbank Demonstration Works / NB-CP |
| Applicable assets | PUMP-001, PUMP-002, PUMP-003 |
| Related documents | SOP-PMP-001 rev 1.0; SOP-PMP-003 rev 1.0 |
| Status | SYNTHETIC TRAINING DOCUMENT - NOT APPROVED FOR REAL EQUIPMENT |

## DIAGNOSTIC-METHOD

Start with time-aligned telemetry and a stated observation interval. Separate
observations from hypotheses. Check related signals that could disprove the
initial interpretation. Report missing evidence explicitly. Overall vibration
cannot identify a specific bearing defect or prove cavitation. No diagnosis in
this demonstration authorizes physical intervention.

## BEARING

Open a bearing-condition WARNING when BOTH bearing_temperature_c >= 75 C and
vibration_mm_s >= 4.0 mm/s persist continuously for at least 30 seconds.
Escalate to CRITICAL when BOTH bearing_temperature_c >= 85 C and
vibration_mm_s >= 6.0 mm/s persist for at least 20 seconds.

Validate the observation against lubricant_pressure_bar, motor_current_a,
motor_temperature_c and ambient_temperature_c. Decreasing lubricant pressure
and increasing current support a friction/lubrication concern, but telemetry
alone does not establish a failed bearing. Compare flow_m3_h and
suction_pressure_bar: stable hydraulic delivery weakens a suction-restriction
hypothesis. Check sensor calibration and mounting if heat and vibration disagree.

Possible impact: accelerated bearing wear, increased drive load, reduced
availability and an unplanned service interruption. These are possible outcomes,
not remaining-useful-life estimates. Ask the qualified operator to review the
trend and inspection history under approved site procedures.

Clear only when BOTH bearing_temperature_c <= 70 C and vibration_mm_s <= 3.0
mm/s remain continuously normal for 30 seconds with fresh, good running data.
A critical alert retains its highest severity until this clear condition is met.
Acknowledgement records operator review; it does not clear the condition.

## SUCTION

Open a suction-condition WARNING when BOTH suction_pressure_bar <= 1.0 bar and
flow_m3_h <= 34 m3/h persist for at least 30 seconds. Escalate to CRITICAL when
ALL THREE suction_pressure_bar <= 0.6 bar, flow_m3_h <= 28 m3/h and
vibration_mm_s >= 4.5 mm/s persist for at least 20 seconds.

Compare discharge_pressure_bar and speed_rpm to distinguish reduced supply from
an intentional speed/duty change. Lower motor_current_a with lower delivered
flow supports unloading. Compare bearing_temperature_c and
lubricant_pressure_bar: a bearing-hot/lubricant-low combination suggests a
different or concurrent concern. Ask for independently verified supply-level,
strainer differential-pressure and valve-position observations; those sensors
are NOT present in this simulator. Do not invent their values.

Possible impact: unstable hydraulic delivery, reduced process circulation and
possible pump degradation. The available gauge pressures do not prove cavitation
or provide sufficient information for an NPSH calculation. Ask a qualified
operator to investigate supply-side conditions using approved procedures.

Clear only when BOTH suction_pressure_bar >= 1.2 bar and flow_m3_h >= 38 m3/h
remain continuously recovered for 30 seconds. Do not clear on missing readings.
Acknowledging an alert does not certify recovery.

## DIFFERENTIAL

Rising bearing heat, rising vibration and falling lubricant pressure with stable
flow favour a bearing/lubrication investigation. Falling suction pressure, falling
flow, lower discharge pressure and increased vibration with a cool bearing favour
a supply-side investigation. If both patterns appear, report multiple hypotheses
and seek operator corroboration rather than forcing a single fault classification.

The healthy reference is context only. Common changes across every asset can
indicate an ambient, duty, source or clock issue rather than independent failures.

## EVIDENCE

Record asset ID, alert ID, rule version, severity, first/last observation times,
window duration, sample count, largest gap, signal min/max/latest, and source
document revision/section. Keep every generated diagnosis linked to its own
evidence snapshot and chosen model. Mark historical/resolved alerts as such.
An AI explanation is advisory; the deterministic rule remains the alert authority.
