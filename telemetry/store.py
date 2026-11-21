import logging
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from telemetry.rules import CRITICAL_SECONDS, RULES, WARNING_SECONDS, severity, summarize, sustained


LOG = logging.getLogger(__name__)


def connect():
    return psycopg.connect(
        connect_timeout=5, row_factory=dict_row,
        application_name="telemetry-analysis",
        options="-c timezone=UTC -c statement_timeout=15000",
    )


def save_alert(conn, equipment, rule_id, level, title, impact, document, section, evidence, related, missing, now):
    current = conn.execute(
        "SELECT id, severity FROM analysis.alerts WHERE equipment_id=%s AND rule_id=%s AND resolved_at IS NULL FOR UPDATE",
        (equipment, rule_id),
    ).fetchone()
    if current:
        elevated = current["severity"] != "critical" and level == "critical"
        conn.execute(
            """UPDATE analysis.alerts SET severity=%s, evidence=%s, last_seen_at=%s WHERE id=%s""",
            ("critical" if current["severity"] == "critical" else level, Jsonb(evidence), now, current["id"]),
        )
        if elevated:
            conn.execute(
                "INSERT INTO analysis.alert_events (alert_id,event_type,detail) VALUES (%s,'escalated','Escalated to critical by sustained rule')",
                (current["id"],),
            )
        return
    identifier = uuid.uuid4()
    conn.execute(
        """INSERT INTO analysis.alerts (
            id,equipment_id,rule_id,rule_revision,severity,title,impact,
            source_document,source_revision,source_section,evidence,
            related_parameters,missing_evidence,opened_at,last_seen_at
        ) VALUES (%s,%s,%s,'1.0',%s,%s,%s,%s,'1.0',%s,%s,%s,%s,%s,%s)""",
        (identifier, equipment, rule_id, level, title, impact, document, section,
         Jsonb(evidence), Jsonb(list(related)), Jsonb(list(missing)), now, now),
    )
    conn.execute(
        "INSERT INTO analysis.alert_events (alert_id,event_type,detail) VALUES (%s,'opened',%s)",
        (identifier, f"SOP rule opened {level} alert"),
    )
    LOG.info("Opened %s alert %s for %s (%s)", level, identifier, equipment, rule_id)


def resolve(conn, equipment, rule_id, now):
    closed = conn.execute(
        """UPDATE analysis.alerts SET resolved_at=%s
           WHERE equipment_id=%s AND rule_id=%s AND resolved_at IS NULL RETURNING id""",
        (now, equipment, rule_id),
    ).fetchone()
    if closed:
        conn.execute(
            "INSERT INTO analysis.alert_events (alert_id,event_type,detail) VALUES (%s,'resolved','Continuous SOP clear condition satisfied')",
            (closed["id"],),
        )
        LOG.info("Resolved alert %s", closed["id"])


def detect_tick():
    with connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_xact_lock(31825003) AS acquired").fetchone()["acquired"]:
            return
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        equipment = conn.execute("SELECT equipment_id FROM telemetry.equipment ORDER BY equipment_id").fetchall()
        samples = conn.execute(
            "SELECT * FROM telemetry.samples WHERE measured_at >= %s - INTERVAL '120 seconds' ORDER BY measured_at",
            (now,),
        ).fetchall()
        for asset in equipment:
            name = asset["equipment_id"]
            rows = [s for s in samples if s["equipment_id"] == name]
            evidence = summarize(rows, now)
            if evidence["stale"]:
                save_alert(
                    conn, name, "telemetry-stale", "warning", "Telemetry is stale or missing",
                    "Equipment condition cannot be reliably assessed; existing mechanical alerts are not cleared.",
                    "SOP-PMP-001", "DATA-QUALITY", evidence, (), ("Fresh time-aligned telemetry",), now,
                )
                continue
            if sustained(rows, (), 20, now):
                resolve(conn, name, "telemetry-stale", now)
            for rule in RULES:
                level = severity(rule, rows, now)
                if level:
                    triggering = rule.critical if level == "critical" else rule.warning
                    trigger_evidence = dict(
                        evidence,
                        required_sustained_seconds=CRITICAL_SECONDS if level == "critical" else WARNING_SECONDS,
                        triggering_conditions=[vars(condition) for condition in triggering],
                    )
                    save_alert(
                        conn, name, rule.id, level, rule.title, rule.impact, rule.document,
                        rule.section, trigger_evidence, rule.related, rule.missing, now,
                    )
                elif sustained(rows, rule.clear, 30, now):
                    resolve(conn, name, rule.id, now)
