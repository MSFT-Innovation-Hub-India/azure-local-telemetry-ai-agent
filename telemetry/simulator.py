"""Publish current-time, correlated pump samples directly to TimescaleDB."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import os
from pathlib import Path
import random
import signal
import threading
import time
import uuid


LOG = logging.getLogger("telemetry.simulator")
HEARTBEAT = Path("/tmp/telemetry-last-write")
EQUIPMENT = ("PUMP-001", "PUMP-002", "PUMP-003")
CYCLE_SECONDS = 600
INSERT = """
INSERT INTO telemetry.samples (
    measured_at, event_id, equipment_id, run_id, sequence, scenario,
    operating_state, quality, speed_rpm, motor_current_a,
    motor_temperature_c, bearing_temperature_c, vibration_mm_s,
    suction_pressure_bar, discharge_pressure_bar, flow_m3_h,
    lubricant_pressure_bar, ambient_temperature_c
) VALUES (
    %(measured_at)s, %(event_id)s, %(equipment_id)s, %(run_id)s,
    %(sequence)s, %(scenario)s, %(operating_state)s, %(quality)s,
    %(speed_rpm)s, %(motor_current_a)s, %(motor_temperature_c)s,
    %(bearing_temperature_c)s, %(vibration_mm_s)s,
    %(suction_pressure_bar)s, %(discharge_pressure_bar)s,
    %(flow_m3_h)s, %(lubricant_pressure_bar)s, %(ambient_temperature_c)s
) ON CONFLICT DO NOTHING
"""


@dataclass(frozen=True)
class Sample:
    measured_at: datetime
    event_id: uuid.UUID
    equipment_id: str
    run_id: uuid.UUID
    sequence: int
    scenario: str
    operating_state: str
    quality: str
    speed_rpm: float
    motor_current_a: float
    motor_temperature_c: float
    bearing_temperature_c: float
    vibration_mm_s: float
    suction_pressure_bar: float
    discharge_pressure_bar: float
    flow_m3_h: float
    lubricant_pressure_bar: float
    ambient_temperature_c: float


def fault_level(elapsed: float) -> float:
    phase = max(0.0, elapsed) % CYCLE_SECONDS
    if phase < 120:
        return 0.0
    if phase < 300:
        return (phase - 120) / 180
    if phase < 420:
        return 1.0
    if phase < 540:
        return (540 - phase) / 120
    return 0.0


def generate_sample(
    equipment_id: str, elapsed: float, measured_at: datetime,
    run_id: uuid.UUID, sequence: int, rng: random.Random,
) -> Sample:
    if equipment_id not in EQUIPMENT:
        raise ValueError(f"Unknown equipment: {equipment_id}")
    if measured_at.tzinfo is None or measured_at.utcoffset() is None:
        raise ValueError("measured_at must be timezone-aware")
    if not math.isfinite(elapsed) or elapsed < 0 or sequence < 0:
        raise ValueError("elapsed must be finite and nonnegative; sequence must be nonnegative")
    level = fault_level(elapsed)
    bearing = level if equipment_id == "PUMP-001" else 0.0
    suction = level if equipment_id == "PUMP-002" else 0.0
    scenario = "normal"
    if bearing > 0:
        scenario = "bearing-degradation"
    elif suction > 0:
        scenario = "suction-restriction"
    load = math.sin(elapsed / 45) * 0.3

    def value(base: float, noise: float) -> float:
        return round(base + rng.uniform(-noise, noise), 3)

    return Sample(
        measured_at.astimezone(timezone.utc), uuid.uuid4(), equipment_id,
        run_id, sequence, scenario, "running", "good",
        value(1480 + load * 2, 2),
        value(18 + load + bearing * 3 - suction * 2, 0.15),
        value(63 + load + bearing * 10, 0.3),
        value(59 + bearing * 31, 0.3),
        value(1.8 + bearing * 5 + suction * 4.2, 0.08),
        value(1.5 - suction * 1.1, 0.015),
        value(5.8 - suction * 1.8, 0.025),
        value(42 + load - suction * 18, 0.15),
        value(2.4 - bearing * 1.1, 0.02),
        value(27 + math.sin(elapsed / 300), 0.1),
    )


def write_batch(connection, samples: list[Sample]) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(INSERT, [vars(sample) for sample in samples])


def run(interval: float) -> None:
    import psycopg

    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    run_id = uuid.uuid4()
    rng = random.Random()
    started = time.monotonic()
    sequence = 0
    connection = None
    retry_delay = 1.0
    pending = None
    try:
        while not stop.is_set():
            if pending is None:
                now = datetime.now(timezone.utc)
                pending = [
                    generate_sample(name, time.monotonic() - started, now, run_id, sequence, rng)
                    for name in EQUIPMENT
                ]
            try:
                if connection is None or connection.closed:
                    # libpq reads PGHOST/PGDATABASE/PGUSER/PGPASSWORD from the environment.
                    connection = psycopg.connect(
                        connect_timeout=10, application_name="pump-simulator",
                        options="-c statement_timeout=15000 -c timezone=UTC",
                    )
                write_batch(connection, pending)
                HEARTBEAT.touch()
                if sequence % 15 == 0:
                    LOG.info(
                        "Committed %d synthetic samples; sequence=%d measured_at=%s scenarios=%s",
                        len(pending), sequence, pending[0].measured_at.isoformat(),
                        ",".join(sample.scenario for sample in pending),
                    )
                pending = None
                sequence += 1
                retry_delay = 1.0
                stop.wait(interval)
            except psycopg.OperationalError as exc:
                # Retry the same event IDs after an uncertain commit; inserts are idempotent.
                LOG.error(
                    "Database unavailable (%s, SQLSTATE=%s); retrying pending batch in %.0fs",
                    type(exc).__name__, exc.sqlstate or "connection", retry_delay,
                )
                if connection is not None:
                    connection.close()
                connection = None
                stop.wait(retry_delay)
                retry_delay = min(30.0, retry_delay * 2)
    finally:
        if connection is not None:
            connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--health-check", action="store_true")
    args = parser.parse_args()
    if args.health_check:
        if not HEARTBEAT.exists() or time.time() - HEARTBEAT.stat().st_mtime > 45:
            raise SystemExit("No successful database write within 45 seconds")
        return
    if not math.isfinite(args.interval) or not 0.5 <= args.interval <= 10:
        parser.error("--interval must be between 0.5 and 10 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if any(not os.environ.get(key) for key in ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")):
        parser.error("PGHOST, PGDATABASE, PGUSER and PGPASSWORD are required")
    run(args.interval)


if __name__ == "__main__":
    main()
