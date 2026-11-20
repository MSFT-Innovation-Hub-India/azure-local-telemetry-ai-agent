\set ON_ERROR_STOP on
SELECT extversion AS timescaledb_version FROM pg_extension WHERE extname = 'timescaledb';
SELECT hypertable_schema, hypertable_name, num_chunks
FROM timescaledb_information.hypertables;
SELECT equipment_id, count(*) AS samples, min(measured_at) AS first_sample,
       max(measured_at) AS latest_sample,
       round(extract(epoch FROM now() - max(measured_at))::numeric, 2) AS age_seconds
FROM telemetry.samples GROUP BY equipment_id ORDER BY equipment_id;
SELECT equipment_id, measured_at, scenario, bearing_temperature_c, vibration_mm_s,
       suction_pressure_bar, discharge_pressure_bar, flow_m3_h, lubricant_pressure_bar
FROM telemetry.latest ORDER BY equipment_id;

SELECT time_bucket('1 minute', measured_at) AS minute, equipment_id,
       round(avg(bearing_temperature_c)::numeric, 2) AS avg_bearing_c,
       round(max(vibration_mm_s)::numeric, 2) AS max_vibration_mm_s,
       round(avg(flow_m3_h)::numeric, 2) AS avg_flow_m3_h
FROM telemetry.samples
WHERE measured_at > now() - INTERVAL '5 minutes'
GROUP BY minute, equipment_id ORDER BY minute DESC, equipment_id;
