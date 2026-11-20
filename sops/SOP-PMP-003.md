# SOP-PMP-003: Inspection, upkeep and return-to-service review

| Document control | Value |
|---|---|
| Revision / effective date | 1.0 / 2026-11-13 |
| Facility / equipment family | Fictional Northbank Demonstration Works / NB-CP |
| Applicable assets | PUMP-001, PUMP-002, PUMP-003 |
| Classification | Demonstration inspection and evidence-retention guidance |
| Status | SYNTHETIC TRAINING DOCUMENT - NOT APPROVED FOR REAL EQUIPMENT |

## RESPONSIBILITIES

The demonstration operator reviews and acknowledges alerts. A qualified
maintenance representative reviews inspection evidence. The AI assistant only
summarizes telemetry and documents; it cannot approve maintenance, operate
equipment, certify safety or close a work order. Use actual manufacturer
instructions, approved isolation procedures and competent personnel for any real
intervention.

## ROUTINE

Suggested fictional review schedule:

| Interval | Review activity | Evidence to record |
|---|---|---|
| Each simulated shift | Review data freshness, open alerts and 60-second trends | Asset, timestamp, missing channels and operator note |
| Weekly training review | Compare bearing, current and vibration patterns | Trend references, prior alerts and competing explanations |
| Monthly training review | Review sensor identity/calibration and document revision | Instrument inventory, calibration status and approved SOP version |
| After any simulated abnormal event | Review correlated signals and acknowledgement history | Alert/diagnosis IDs, model choice, source citations and observed recovery |

These intervals are invented training examples, not maintenance instructions for
an actual pump. Physical tasks and intervals must come from the real equipment
manufacturer and the site's approved maintenance system.

## BEARING-REVIEW

Review the SOP-PMP-002 BEARING evidence before declaring a lubrication or bearing
issue. Check whether lubricant pressure fell before, during or after heat and
vibration rose. Compare motor current, ambient and flow to challenge the
hypothesis. Obtain maintenance/calibration history and inspection observations
from authorized personnel; the database does not contain these observations.
Do not infer a specific damaged component from overall vibration alone.

## SUPPLY-REVIEW

For a suction-condition event, correlate suction/discharge pressures, flow,
speed and current over the same interval. Request supply-level, valve-position
and strainer observations separately. Their absence is a diagnostic limitation,
not a reason to synthesize readings. A technician must determine any required
physical inspection using approved site practices.

## RECOVERY

Automatic alert resolution means only that the documented clear condition
persisted with fresh data. It does not certify mechanical condition or authorize
return to service. Keep the highest observed severity, acknowledgement and
resolution times. Preserve generated explanations as historical records even if
later readings contradict them. A later recurrence must create a new alert.

## RECORDS

Store original SOP text with its ID, immutable revision and checksum. Store
embeddings separately and retain document/section references with every retrieved
passage. Reindexing must not overwrite the warranty assistant's collections.
Record model identity, evidence time and token usage when provided by the model.
If retrieval or inference fails, display the failure and leave deterministic
alert detection running.
