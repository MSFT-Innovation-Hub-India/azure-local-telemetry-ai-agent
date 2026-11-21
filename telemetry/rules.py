"""Deterministic, SOP-versioned detection; simulator scenario labels are never read."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import operator


FIELDS = (
    "speed_rpm", "motor_current_a", "motor_temperature_c", "bearing_temperature_c",
    "vibration_mm_s", "suction_pressure_bar", "discharge_pressure_bar",
    "flow_m3_h", "lubricant_pressure_bar", "ambient_temperature_c",
)
OPS = {">=": operator.ge, "<=": operator.le}
CRITICAL_SECONDS = 20
WARNING_SECONDS = 30


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: float

    def matches(self, sample):
        return OPS[self.op](sample[self.field], self.value)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    document: str
    section: str
    impact: str
    warning: tuple[Condition, ...]
    critical: tuple[Condition, ...]
    clear: tuple[Condition, ...]
    related: tuple[str, ...]
    missing: tuple[str, ...] = ()
    revision: str = "1.0"


RULES = (
    Rule(
        "bearing", "Bearing / lubrication condition", "SOP-PMP-002", "BEARING",
        "Possible accelerated bearing wear, increased drive load and an unplanned service interruption.",
        (Condition("bearing_temperature_c", ">=", 75), Condition("vibration_mm_s", ">=", 4)),
        (Condition("bearing_temperature_c", ">=", 85), Condition("vibration_mm_s", ">=", 6)),
        (Condition("bearing_temperature_c", "<=", 70), Condition("vibration_mm_s", "<=", 3)),
        ("lubricant_pressure_bar", "motor_current_a", "motor_temperature_c",
         "ambient_temperature_c", "flow_m3_h", "suction_pressure_bar"),
        ("Sensor calibration and mounting observations", "Maintenance and inspection history"),
    ),
    Rule(
        "suction", "Suction / hydraulic delivery condition", "SOP-PMP-002", "SUCTION",
        "Possible unstable hydraulic delivery, reduced process circulation and pump degradation; cavitation is not proven.",
        (Condition("suction_pressure_bar", "<=", 1), Condition("flow_m3_h", "<=", 34)),
        (Condition("suction_pressure_bar", "<=", 0.6), Condition("flow_m3_h", "<=", 28),
         Condition("vibration_mm_s", ">=", 4.5)),
        (Condition("suction_pressure_bar", ">=", 1.2), Condition("flow_m3_h", ">=", 38)),
        ("discharge_pressure_bar", "speed_rpm", "motor_current_a",
         "bearing_temperature_c", "lubricant_pressure_bar"),
        ("Independently verified supply level", "Strainer differential pressure", "Valve position"),
    ),
)


def sustained(samples, conditions, seconds, now):
    rows = sorted(
        (s for s in samples if s["measured_at"] <= now),
        key=lambda s: s["measured_at"],
    )
    cutoff = now - timedelta(seconds=seconds)
    anchors = [s for s in rows if s["measured_at"] <= cutoff]
    if not anchors:
        return False
    window = [anchors[-1]] + [s for s in rows if s["measured_at"] > cutoff]
    if (
        (cutoff - window[0]["measured_at"]).total_seconds() > 6
        or (now - window[-1]["measured_at"]).total_seconds() > 6
        or any((b["measured_at"] - a["measured_at"]).total_seconds() > 6 for a, b in zip(window, window[1:]))
    ):
        return False
    return all(
        s["quality"] == "good" and s["operating_state"] == "running"
        and all(condition.matches(s) for condition in conditions)
        for s in window
    )


def severity(rule, samples, now):
    if sustained(samples, rule.critical, CRITICAL_SECONDS, now):
        return "critical"
    if sustained(samples, rule.warning, WARNING_SECONDS, now):
        return "warning"
    return None


def summarize(samples, now):
    rows = sorted(
        (s for s in samples if now - timedelta(seconds=60) <= s["measured_at"] <= now),
        key=lambda s: s["measured_at"],
    )
    if not rows:
        return {"assessed_at": now.isoformat(), "sample_count": 0, "signals": {}, "stale": True}
    return {
        "assessed_at": now.isoformat(), "window_start": rows[0]["measured_at"].isoformat(),
        "window_end": rows[-1]["measured_at"].isoformat(), "sample_count": len(rows),
        "largest_gap_seconds": max(
            ((b["measured_at"] - a["measured_at"]).total_seconds() for a, b in zip(rows, rows[1:])),
            default=0,
        ),
        "stale": (now - rows[-1]["measured_at"]).total_seconds() > 15,
        "signals": {
            field: {"latest": rows[-1][field], "min": min(s[field] for s in rows), "max": max(s[field] for s in rows)}
            for field in FIELDS
        },
    }
