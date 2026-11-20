"""Read-only views of what is physically stored in the telemetry hypertable."""

import logging
import os
import threading
import time

import psycopg

from telemetry.rules import FIELDS
from telemetry.store import connect


LOG = logging.getLogger(__name__)
VOLUME_BYTES = int(float(os.environ.get("TELEMETRY_VOLUME_GIB", "20")) * 1024 ** 3)
CLOSED_DAYS_TTL_SECONDS = 300
SAMPLE_COLUMNS = ("measured_at", "ingested_at", "event_id", "sequence", "scenario", "quality", "operating_state") + FIELDS

# Rows older than today's UTC midnight only change when retention drops chunks,
# so their count is cached; today's rows are counted exactly on every request.
_closed = {"cutoff": None, "expires": 0.0, "counts": {}}
_lock = threading.Lock()


def _closed_counts(conn, cutoff):
    with _lock:
        if _closed["cutoff"] == cutoff and time.monotonic() < _closed["expires"]:
            return _closed["counts"]
    rows = conn.execute(
        "SELECT equipment_id,count(*) AS n FROM telemetry.samples WHERE measured_at < %s GROUP BY equipment_id", (cutoff,),
    ).fetchall()
    counts = {row["equipment_id"]: row["n"] for row in rows}
    with _lock:
        _closed.update(cutoff=cutoff, expires=time.monotonic() + CLOSED_DAYS_TTL_SECONDS, counts=counts)
    return counts


def _optional(conn, sql):
    """Run a metadata query that may be unavailable to the read-only role without failing the page."""
    try:
        with conn.transaction():
            return conn.execute(sql).fetchone()
    except psycopg.Error as exc:
        LOG.warning("Optional storage metadata unavailable (%s)", type(exc).__name__)
        return None


def summary():
    with connect() as conn:
        head = conn.execute(
            "SELECT clock_timestamp() AS now, date_trunc('day', clock_timestamp()) AS cutoff",
        ).fetchone()
        closed = _closed_counts(conn, head["cutoff"])
        today = {
            row["equipment_id"]: row for row in conn.execute(
                """SELECT equipment_id,count(*) AS n,
                          count(*) FILTER (WHERE measured_at > %s - INTERVAL '60 seconds') AS recent
                   FROM telemetry.samples WHERE measured_at >= %s GROUP BY equipment_id""",
                (head["now"], head["cutoff"]),
            ).fetchall()
        }
        assets = conn.execute(
            """SELECT e.equipment_id,e.description,
                      (SELECT measured_at FROM telemetry.samples s WHERE s.equipment_id=e.equipment_id ORDER BY measured_at ASC LIMIT 1) AS first_sample,
                      (SELECT measured_at FROM telemetry.samples s WHERE s.equipment_id=e.equipment_id ORDER BY measured_at DESC LIMIT 1) AS latest_sample
               FROM telemetry.equipment e ORDER BY e.equipment_id""",
        ).fetchall()
        sizes = _optional(
            conn, "SELECT hypertable_size('telemetry.samples') AS samples_bytes, pg_database_size(current_database()) AS database_bytes",
        )
        chunks = _optional(
            conn, """SELECT count(*) AS chunks FROM timescaledb_information.chunks
                     WHERE hypertable_schema='telemetry' AND hypertable_name='samples'""",
        )
        retention = _optional(
            conn, """SELECT config->>'drop_after' AS retention FROM timescaledb_information.jobs
                     WHERE proc_name='policy_retention' AND hypertable_schema='telemetry' AND hypertable_name='samples'""",
        )
    for asset in assets:
        live = today.get(asset["equipment_id"], {"n": 0, "recent": 0})
        asset["rows"] = closed.get(asset["equipment_id"], 0) + live["n"]
        asset["rows_last_minute"] = live["recent"]
    firsts = [a["first_sample"] for a in assets if a["first_sample"]]
    latests = [a["latest_sample"] for a in assets if a["latest_sample"]]
    return {
        "server_time": head["now"],
        "total_rows": sum(a["rows"] for a in assets),
        "rows_last_minute": sum(a["rows_last_minute"] for a in assets),
        "first_sample": min(firsts) if firsts else None,
        "latest_sample": max(latests) if latests else None,
        "equipment": assets,
        "storage": {
            "samples_bytes": sizes and sizes["samples_bytes"],
            "database_bytes": sizes and sizes["database_bytes"],
            "volume_bytes": VOLUME_BYTES,
            "chunks": chunks and chunks["chunks"],
            "retention": retention and retention["retention"],
        },
    }


def recent(equipment_id, limit):
    """Newest stored rows for one asset, or None when the asset is not in the inventory."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM telemetry.equipment WHERE equipment_id=%s", (equipment_id,)).fetchone():
            return None
        return conn.execute(
            f"SELECT {','.join(SAMPLE_COLUMNS)} FROM telemetry.samples WHERE equipment_id=%s ORDER BY measured_at DESC LIMIT %s",
            (equipment_id, limit),
        ).fetchall()
