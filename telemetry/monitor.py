"""Read-only rule monitor: shows each SOP rule's conditions, current state and recent history.

The thresholds come from telemetry.rules, so this view cannot drift from the detector.
Nothing here opens, changes or clears an alert.
"""

from telemetry.rules import CRITICAL_SECONDS, FIELDS, OPS, RULES, WARNING_SECONDS
from telemetry.store import connect


BUCKET_SECONDS = 5
CONDITIONS = tuple(dict.fromkeys(c for rule in RULES for c in rule.warning + rule.critical))
INDEX = {condition: i for i, condition in enumerate(CONDITIONS)}
assert all(c.field in FIELDS and c.op in OPS for c in CONDITIONS)

# A bucket violates a condition only if every sample in it does, so a violation is continuous.
FLAGS_SQL = f"""SELECT equipment_id,time_bucket('{BUCKET_SECONDS} seconds',measured_at) AS bucket,
    {",".join(f"bool_and({c.field} {c.op} %s) AS c{i}" for i, c in enumerate(CONDITIONS))}
    FROM telemetry.samples WHERE measured_at > %s - %s * INTERVAL '1 second'
    GROUP BY equipment_id,bucket"""


def condition_json(condition):
    return {"field": condition.field, "op": condition.op, "value": condition.value}


def definitions():
    return [{
        "id": rule.id, "title": rule.title, "document": rule.document, "section": rule.section,
        "sustained_seconds": {"warning": WARNING_SECONDS, "critical": CRITICAL_SECONDS},
        "warning": [condition_json(c) for c in rule.warning],
        "critical": [condition_json(c) for c in rule.critical],
    } for rule in RULES]


def thresholds():
    found = {}
    for rule in RULES:
        for level, conditions in (("warning", rule.warning), ("critical", rule.critical)):
            for c in conditions:
                found.setdefault(c.field, []).append({"level": level, "op": c.op, "value": c.value, "rule": rule.id})
    return found


def trailing_run(values):
    """Seconds the series has been continuously 1, ignoring one empty bucket for the interval in progress."""
    index = len(values) - 1
    if index >= 0 and values[index] is None:
        index -= 1
    count = 0
    while index >= 0 and values[index] == 1:
        count += 1
        index -= 1
    return count * BUCKET_SECONDS


def build(now, seconds, rows, latest, alerts, equipment_ids):
    count = seconds // BUCKET_SECONDS + 1
    first = int(now.timestamp() // BUCKET_SECONDS) * BUCKET_SECONDS - (count - 1) * BUCKET_SECONDS
    grid = {}
    for row in rows:
        position = (int(row["bucket"].timestamp()) - first) // BUCKET_SECONDS
        if 0 <= position < count:
            grid.setdefault(row["equipment_id"], {})[position] = row
    open_alerts = {(a["equipment_id"], a["rule_id"]): a for a in alerts}

    def series(equipment_id, conditions):
        buckets = grid.get(equipment_id, {})
        values = []
        for position in range(count):
            row = buckets.get(position)
            values.append(None if row is None else int(all(row[f"c{INDEX[c]}"] for c in conditions)))
        return values

    equipment = []
    for equipment_id in equipment_ids:
        sample = latest.get(equipment_id)
        rules = []
        for rule in RULES:
            levels = {}
            for level, conditions in (("warning", rule.warning), ("critical", rule.critical)):
                combined = series(equipment_id, conditions)
                met = [bool(sample and OPS[c.op](sample[c.field], c.value)) for c in conditions]
                levels[level] = {"met": met, "all_met": all(met), "streak_seconds": trailing_run(combined), "series": combined}
            alert = open_alerts.get((equipment_id, rule.id))
            rules.append({
                "rule_id": rule.id,
                "alert": alert and {"severity": alert["severity"], "opened_at": alert["opened_at"],
                                    "acknowledged": bool(alert["acknowledged_at"])},
                "conditions": [series(equipment_id, (c,)) for c in rule.warning],
                "warning": levels["warning"], "critical": levels["critical"],
            })
        equipment.append({
            "equipment_id": equipment_id,
            "latest": sample and {f: sample[f] for f in ("measured_at",) + FIELDS},
            "rules": rules,
        })
    return {
        "server_time": now, "window_seconds": seconds, "bucket_seconds": BUCKET_SECONDS, "bucket_count": count,
        "first_bucket_epoch": first, "rules": definitions(), "thresholds": thresholds(), "equipment": equipment,
    }


def monitor(minutes):
    seconds = minutes * 60
    with connect() as conn:
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        rows = conn.execute(FLAGS_SQL, [c.value for c in CONDITIONS] + [now, seconds]).fetchall()
        latest = {
            r["equipment_id"]: r for r in conn.execute(
                "SELECT equipment_id,measured_at," + ",".join(FIELDS) + " FROM telemetry.latest",
            ).fetchall()
        }
        alerts = conn.execute(
            "SELECT equipment_id,rule_id,severity,opened_at,acknowledged_at FROM analysis.alerts WHERE resolved_at IS NULL",
        ).fetchall()
        ids = [r["equipment_id"] for r in conn.execute("SELECT equipment_id FROM telemetry.equipment ORDER BY equipment_id").fetchall()]
    return build(now, seconds, rows, latest, alerts, ids)
