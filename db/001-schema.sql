\set ON_ERROR_STOP on
\getenv writer_password WRITER_PASSWORD
\getenv reader_password READER_PASSWORD

CREATE EXTENSION IF NOT EXISTS timescaledb;
ALTER DATABASE telemetry SET timezone TO 'UTC';
CREATE SCHEMA telemetry;

CREATE TABLE telemetry.equipment (
    equipment_id text PRIMARY KEY,
    description text NOT NULL,
    synthetic boolean NOT NULL DEFAULT true CHECK (synthetic)
);
INSERT INTO telemetry.equipment VALUES
    ('PUMP-001', 'Fictional centrifugal pump: bearing degradation cycle', true),
    ('PUMP-002', 'Fictional centrifugal pump: suction restriction cycle', true),
    ('PUMP-003', 'Fictional centrifugal pump: healthy reference', true);

CREATE TABLE telemetry.samples (
    measured_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    event_id uuid NOT NULL,
    equipment_id text NOT NULL REFERENCES telemetry.equipment,
    run_id uuid NOT NULL,
    sequence bigint NOT NULL CHECK (sequence >= 0),
    scenario text NOT NULL CHECK (scenario IN ('normal', 'bearing-degradation', 'suction-restriction')),
    operating_state text NOT NULL CHECK (operating_state IN ('running')),
    quality text NOT NULL CHECK (quality IN ('good')),
    speed_rpm double precision NOT NULL CHECK (speed_rpm BETWEEN 0 AND 3000),
    motor_current_a double precision NOT NULL CHECK (motor_current_a BETWEEN 0 AND 100),
    motor_temperature_c double precision NOT NULL CHECK (motor_temperature_c BETWEEN -40 AND 200),
    bearing_temperature_c double precision NOT NULL CHECK (bearing_temperature_c BETWEEN -40 AND 200),
    vibration_mm_s double precision NOT NULL CHECK (vibration_mm_s BETWEEN 0 AND 50),
    suction_pressure_bar double precision NOT NULL CHECK (suction_pressure_bar BETWEEN 0 AND 20),
    discharge_pressure_bar double precision NOT NULL CHECK (discharge_pressure_bar BETWEEN 0 AND 40),
    flow_m3_h double precision NOT NULL CHECK (flow_m3_h BETWEEN 0 AND 200),
    lubricant_pressure_bar double precision NOT NULL CHECK (lubricant_pressure_bar BETWEEN 0 AND 20),
    ambient_temperature_c double precision NOT NULL CHECK (ambient_temperature_c BETWEEN -40 AND 80),
    PRIMARY KEY (measured_at, event_id)
);
SELECT create_hypertable('telemetry.samples', 'measured_at', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON telemetry.samples (equipment_id, measured_at DESC);
SELECT add_retention_policy('telemetry.samples', INTERVAL '7 days');

CREATE VIEW telemetry.latest AS
SELECT DISTINCT ON (equipment_id) *
FROM telemetry.samples
ORDER BY equipment_id, measured_at DESC;

CREATE ROLE telemetry_writer LOGIN PASSWORD :'writer_password';
CREATE ROLE telemetry_reader LOGIN PASSWORD :'reader_password';
REVOKE ALL ON DATABASE telemetry FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE telemetry TO telemetry_writer, telemetry_reader;
GRANT USAGE ON SCHEMA telemetry TO telemetry_writer, telemetry_reader;
GRANT INSERT ON telemetry.samples TO telemetry_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA telemetry TO telemetry_reader;
