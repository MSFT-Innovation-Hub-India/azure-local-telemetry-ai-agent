\set ON_ERROR_STOP on
BEGIN;
SAVEPOINT writer_probe;
SET LOCAL ROLE telemetry_writer;
INSERT INTO telemetry.samples (
    measured_at, event_id, equipment_id, run_id, sequence, scenario,
    operating_state, quality, speed_rpm, motor_current_a, motor_temperature_c,
    bearing_temperature_c, vibration_mm_s, suction_pressure_bar,
    discharge_pressure_bar, flow_m3_h, lubricant_pressure_bar, ambient_temperature_c
)
VALUES (
    now(), '00000000-0000-4000-8000-000000000001', 'PUMP-003',
    '00000000-0000-4000-8000-000000000002', 0, 'normal', 'running',
    'good', 1480, 18, 63, 59, 1.8, 1.5, 5.8, 42, 2.4, 27
)
ON CONFLICT DO NOTHING;
RESET ROLE;
ROLLBACK TO SAVEPOINT writer_probe;
DO $$
DECLARE
    before_count bigint;
    after_count bigint;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_schema = 'telemetry' AND hypertable_name = 'samples'
    ) THEN
        RAISE EXCEPTION 'telemetry.samples is not a hypertable';
    END IF;
    IF (SELECT count(*) FROM telemetry.latest WHERE measured_at > now() - INTERVAL '15 seconds') != 3 THEN
        RAISE EXCEPTION 'Expected fresh live samples from all three pumps';
    END IF;
    IF EXISTS (SELECT 1 FROM telemetry.samples WHERE measured_at > now() + INTERVAL '5 seconds') THEN
        RAISE EXCEPTION 'Unexpected future sample timestamp';
    END IF;
    IF NOT has_table_privilege('telemetry_writer', 'telemetry.samples', 'INSERT')
       OR has_table_privilege('telemetry_writer', 'telemetry.samples', 'SELECT')
       OR has_table_privilege('telemetry_writer', 'telemetry.samples', 'UPDATE')
       OR has_table_privilege('telemetry_writer', 'telemetry.samples', 'DELETE') THEN
        RAISE EXCEPTION 'Writer privileges are not insert-only';
    END IF;
    IF NOT has_table_privilege('telemetry_reader', 'telemetry.samples', 'SELECT')
       OR has_table_privilege('telemetry_reader', 'telemetry.samples', 'INSERT') THEN
        RAISE EXCEPTION 'Reader privileges are not read-only';
    END IF;
    -- Lock only this demo table briefly so concurrent simulation cannot affect the count.
    LOCK TABLE telemetry.samples IN SHARE ROW EXCLUSIVE MODE;
    SELECT count(*) INTO before_count FROM telemetry.samples;
    INSERT INTO telemetry.samples
    SELECT * FROM telemetry.samples ORDER BY measured_at DESC LIMIT 1
    ON CONFLICT DO NOTHING;
    SELECT count(*) INTO after_count FROM telemetry.samples;
    IF before_count != after_count THEN
        RAISE EXCEPTION 'Retrying an existing event inserted a duplicate';
    END IF;
END;
$$;
ROLLBACK;
