\set ON_ERROR_STOP on
\if :{?app_password}
\else
\getenv app_password APP_PASSWORD
\endif
BEGIN;
SELECT pg_advisory_xact_lock(31825002);
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE TABLE IF NOT EXISTS analysis.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analysis.sop_documents (
    document_id text NOT NULL,
    revision text NOT NULL,
    title text NOT NULL,
    sha256 text NOT NULL,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, revision)
);
CREATE TABLE IF NOT EXISTS analysis.sop_active (
    document_id text PRIMARY KEY,
    revision text NOT NULL,
    FOREIGN KEY (document_id, revision) REFERENCES analysis.sop_documents
);
CREATE TABLE IF NOT EXISTS analysis.index_status (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    collection_name text NOT NULL,
    content_sha256 text NOT NULL,
    chunk_count integer NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analysis.alerts (
    id uuid PRIMARY KEY,
    equipment_id text NOT NULL REFERENCES telemetry.equipment,
    rule_id text NOT NULL,
    rule_revision text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('warning', 'critical')),
    title text NOT NULL,
    impact text NOT NULL,
    source_document text NOT NULL,
    source_revision text NOT NULL,
    source_section text NOT NULL,
    evidence jsonb NOT NULL,
    related_parameters jsonb NOT NULL,
    missing_evidence jsonb NOT NULL,
    opened_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_at timestamptz,
    acknowledgement_note text,
    resolved_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_alert
    ON analysis.alerts (equipment_id, rule_id) WHERE resolved_at IS NULL;
CREATE TABLE IF NOT EXISTS analysis.alert_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id uuid NOT NULL REFERENCES analysis.alerts,
    event_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    detail text NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis.diagnoses (
    id uuid PRIMARY KEY,
    alert_id uuid NOT NULL REFERENCES analysis.alerts,
    model_id text NOT NULL,
    result text NOT NULL,
    evidence jsonb NOT NULL,
    sources jsonb NOT NULL,
    usage jsonb,
    elapsed_seconds double precision NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
SELECT format('CREATE ROLE telemetry_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_app') \gexec
GRANT CONNECT ON DATABASE telemetry TO telemetry_app;
GRANT USAGE ON SCHEMA telemetry, analysis TO telemetry_app;
GRANT SELECT ON ALL TABLES IN SCHEMA telemetry TO telemetry_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA analysis TO telemetry_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA analysis TO telemetry_app;
INSERT INTO analysis.schema_migrations (version) VALUES (2) ON CONFLICT DO NOTHING;
COMMIT;
