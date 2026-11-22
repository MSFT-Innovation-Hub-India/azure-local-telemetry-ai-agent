# Code, configuration and extension guide

This guide describes the existing implementation, not a proposed redesign.
For component relationships see [architecture](ARCHITECTURE.md); for commands
that write to Kubernetes see [deployment](DEPLOYMENT.md).

## 1. Repository map

| Path | Responsibility |
|---|---|
| [Dockerfile](../Dockerfile) | Shared Python image; default process is the simulator; app Deployment overrides the command |
| [requirements.txt](../requirements.txt) | Pinned direct runtime dependencies |
| [.dockerignore](../.dockerignore) | Allowlist of code, SOPs and static assets sent to ACR; excludes local credentials/venv |
| [.gitignore](../.gitignore) | Excludes local state, credentials/config and generated Python files |
| [telemetry/simulator.py](../telemetry/simulator.py) | Synthetic signal generation, transactional ingestion, retry/heartbeat |
| [telemetry/rules.py](../telemetry/rules.py) | Immutable rule definitions, sustained windows, severity and summaries |
| [telemetry/store.py](../telemetry/store.py) | Connections, detector transaction, incident persistence and resolution |
| [telemetry/datastore.py](../telemetry/datastore.py) | Read-only data-store panel queries: row counts, first/latest sample, storage size, newest rows |
| [telemetry/monitor.py](../telemetry/monitor.py) | Read-only rule monitor: per-condition and combined violation history (TimescaleDB `time_bucket` + `bool_and`), current state and chart thresholds, all derived from `rules.py` |
| [telemetry/knowledge.py](../telemetry/knowledge.py) | Original SOP seeding, chunking, vectors, retrieval, model allowlist and streaming/non-streaming completions |
| [telemetry/app.py](../telemetry/app.py) | FastAPI lifecycle, independent threads, routes, acknowledgement and diagnosis orchestration |
| [static/index.html](../static/index.html) | Independent dashboard structure and controls |
| [static/app.js](../static/app.js) | API access, polling, charts, model selection, alert/evidence/history rendering |
| [static/style.css](../static/style.css) | Dashboard layout and presentation |
| [sops/catalog.json](../sops/catalog.json) | Document IDs, immutable revisions, titles and packaged filenames |
| [sops/](../sops/) | Three clearly labeled synthetic SOP originals |
| [db/001-schema.sql](../db/001-schema.sql) | Empty-volume initialization: roles, inventory, hypertable, indexes, latest view and retention |
| [db/002-analysis.sql](../db/002-analysis.sql) | Idempotent transactional migration for documents, alerts, events and diagnoses |
| [db/inspect.sql](../db/inspect.sql) | Read-only extension, hypertable, freshness and trend inspection |
| [deploy/stack.yaml](../deploy/stack.yaml) | Foundation templates, quota, storage, policies and security contexts |
| [deploy/analysis.yaml](../deploy/analysis.yaml) | Telemetry web Service/Deployment and additive egress/database policies |
| [deploy/shared-access.yaml](../deploy/shared-access.yaml) | Narrow shared-namespace Qdrant/embedding ingress permission |
| [tools/build_acr.ps1](../tools/build_acr.ps1) | Remote builds/imports, digest resolution and local image metadata |
| [tools/start-demo.ps1](../tools/start-demo.ps1) | Laptop access: kubectl context, Arc proxy (reused if present) and demo port-forwards |
| [tools/deploy.py](../tools/deploy.py) | Foundation deployment, common kubectl/capacity/ownership/placement helpers |
| [tools/deploy_analysis.py](../tools/deploy_analysis.py) | Independent app deployment, shared credential/trust copy and analysis migration |
| [tests/](../tests/) | Unit tests plus live SQL integration checks |
| [docs/](./) | Architecture, setup, code and operations documentation |

The Docker build sends only the allowlisted inputs. Manifests, migration files,
tests, docs and `.local` are not copied into the runtime image. The deployer
creates the initialization ConfigMap and sends the analysis migration separately.
SOP changes do require a new app image because the originals are packaged in it.

## 2. Key implementation entry points

### Simulator

- `Sample`: explicit typed measurement payload with unit-bearing field names.
- `fault_level()`: repeating ramp/hold/recovery waveform.
- `generate_sample()`: asset validation, UTC normalization and correlated values.
- `write_batch()`: one transaction and `executemany` for the pending batch.
- `run()`: one run ID, fresh event time per batch, graceful stop, connection retries
  with 1-30 second backoff and heartbeat only after successful commit.
- `main()`: validates `--interval` (0.5-10 s), DB environment and `--health-check`.

Only operational database failures are retried. Other schema/permission/programming
failures terminate visibly. Health checks require a successful commit within 45 s;
there is deliberately no restart loop driven by a simulator liveness probe.

### Rules and store

`Condition` and `Rule` dataclasses describe the two mechanical conditions.
`sustained()` checks the complete anchored window, quality/state and gaps;
`severity()` tries critical before warning. `summarize()` exposes only named
measurement fields, never scenario labels.

`connect()` uses libpq environment variables, dict rows, a five-second connection
timeout, UTC and a 15-second statement timeout. `detect_tick()` performs one
advisory-locked transaction across registered assets. `save_alert()` updates
evidence, keeps critical severity sticky and writes lifecycle events.
`resolve()` records closure only after a clear window. The DB unique index is
the final guard against duplicate active incidents.

### Knowledge and model client

- `seed_documents()` validates revisions and rule-section references before
  starting background workers.
- `chunks()` uses explicit uppercase section IDs, not arbitrary paragraph overlap.
- `Knowledge.embed()` verifies the exact model/revision and finite vector shapes.
- `Knowledge.index()` performs content-addressed, deterministic upserts and
  publishes DB index status after checking the expected count.
- `Knowledge.retrieve()` refuses non-telemetry collection names and queries the
  current collection using Qdrant's REST API.
- `load_models()` restricts the allowed deployment IDs and Service URLs.
- `parse_completion()` assembles SSE deltas and `parse_response()` reads a
  non-streaming JSON response; both share `finalize()`, which requires a supported
  finish reason, checks supplied source IDs/usage and labels reported output truncation.
- `complete()` applies CA verification, API-key auth, the bounded evidence prompt,
  temperature 0 and a 384-token output request, in streaming or non-streaming mode.
  `STREAMING_RECOMMENDED` lists models that need streaming (14B) to avoid the
  gateway's 60-second non-streaming limit; streaming returns no token counts.

Validation of a source identifier is not validation of the sentence containing it.
Prompt instructions and `temperature=0` do not make a model deterministic across
all runtime versions or make its output factually reliable.

### Application and UI

`lifespan()` seeds documents and starts separate detector/indexer threads.
Index outages do not block detector ticks. Unexpected startup configuration
errors remain explicit failures.

`diagnose()` validates the chosen model/index, takes a nonblocking process-local
lock, reads bounded telemetry, adds the exact supporting SOP section plus
retrieved passages, invokes the model and saves its result. No LLM-generated
query or executable tool instruction is accepted.

The vanilla-JavaScript UI polls overview/trends approximately every five seconds,
draws ten-minute charts with five-second averages, and displays alert details,
events, source text and saved diagnoses. Model selection is remembered under
`telemetry-model` in this application's origin-local storage. The UI escapes
dynamic text; model output is shown as text, not executable HTML/Markdown.
Its selected-alert evidence is refreshed when local inference is not busy.

The dashboard's **Fieldnote** identity uses warm paper, graphite and copper,
editorial headings and monospaced instrument readings. Theme tokens live in
`static/style.css`; the canvas reads those same tokens. Series have distinct
solid/dashed/dotted strokes as well as colors. The design uses system fonts and
an inline SVG mark, with no external font/image requests. All original API and
control IDs remain unchanged; branding does not change alert or model behavior.

Keep the Deployment at one replica with `--workers 1`. Additional workers would
have separate inference locks and background indexer state; replicas are not an
implemented scaling strategy.

## 3. Runtime configuration

| Setting | Default / source |
|---|---|
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` | libpq environment; Deployment sets host/database/role/Secret reference; default port 5432 |
| `CREDENTIALS_DIR` | `/run/credentials`; files named `qdrant-key` and `model-key-<deployment-id>` |
| `MODELS_FILE` | `/run/models/models.json`, mounted catalog |
| `MODEL_CA_FILE` | `/run/trust/ca.crt`, mounted public CA |
| `QDRANT_URL` | `http://qdrant.assistant-demo.svc.cluster.local:6333` |
| `EMBEDDING_URL` | `http://embeddings.assistant-demo.svc.cluster.local:8001` |
| Simulator `--interval` | 2.0 seconds; manifest currently uses the image default |

Environment overrides do not automatically change egress policies or the
deployer's credential-source checks. A different endpoint therefore needs a
coordinated configuration/network/trust review.

## 4. HTTP API

FastAPI also exposes its normal OpenAPI document and interactive `/docs` page.
These are lab interfaces, not authenticated production API endpoints.

| Method / path | Contract |
|---|---|
| GET `/` | Dashboard |
| GET `/healthz` | Process health; `{"status":"ok"}` |
| GET `/readyz` | Recent detector tick; 503 if absent or older than 25 s |
| GET `/api/overview` | `server_time`, equipment, newest 100 alerts, documents, public model IDs/labels, detector/index state, busy flag |
| GET `/api/trends?seconds=600` | Five-second means; accepts 60-1,800 seconds |
| GET `/api/rules/monitor?minutes=10` | Rule definitions and thresholds from `rules.py`, per asset/rule current condition state, open alert, streak of continuous combined violation and five-second history lanes (`1` violated, `0` not, `null` no data) for the window (1-30 minutes). A bucket counts as violating only if every sample in it does. Display-only; it never changes alerts |
| GET `/api/data/summary` | Exact total and per-asset row counts, first/latest sample, rows in the last minute, hypertable/database size, chunk count and retention window. Rows older than today's UTC midnight are cached for 5 minutes; today's rows are counted live. Size, chunk and retention fields are null if the read-only role cannot read them. `TELEMETRY_VOLUME_GIB` (default 20) sets the volume size used for the usage bar |
| GET `/api/data/recent?equipment_id=PUMP-001&limit=20` | Newest stored rows for one asset (1-100); 404 for an unknown asset |
| GET `/api/documents/{id}?revision=1.0` | Original Markdown text; 404 if unavailable |
| GET `/api/alerts/{uuid}` | Alert, complete event history and latest 20 saved diagnoses |
| POST `/api/alerts/{uuid}/acknowledge` | JSON `{"note":"..."}`, maximum 500 characters |
| POST `/api/alerts/{uuid}/diagnose` | JSON `{"model":"qwen2-5-14b-cpu","stream":true}`; `stream` is optional and defaults to streaming for 14B and non-streaming for 0.5B (non-streaming reports token counts but the gateway may cut 14B off after ~60 s); no implicit model fallback |

A successful diagnosis returns `id`, `model_id`, `result`, `evidence`, `sources`,
`usage` (object or null), `elapsed_seconds` and `exchange`: the request body sent
to the model (resolved model name, system and user messages, temperature, output
limit; never the API key) and the response (`content` without the application's
truncation notice, `finish_reason`). `exchange` is stored in the nullable
`analysis.diagnoses.exchange` column, added idempotently by `db/002-analysis.sql`
when the app is deployed; earlier diagnoses have `null`. Model IDs exposed here are the
deployment-selection IDs, not necessarily the inference API's resolved model name.
Acknowledgement returns `{"status":"acknowledged"}`; repeating it adds no second
acknowledgement event. A resolved alert cannot be acknowledged, but can receive a
historical diagnosis with current observations explicitly separated.

Expected errors include 404 for missing alert/document, 422 for invalid input or
unknown chosen model, 409 for busy inference/resolved acknowledgement, 503 for
database/retrieval/inference failure, and 403 for rejected cross-origin mutations.
Error responses use a `detail` field; dependency failures are logged.
Same-origin checks apply to mutations with an Origin header and are not user
authentication. Never expose this app publicly as-is.

## 5. Local tests and deployment tooling

From the project root, using the existing venv:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m tools.deploy --help
.\.venv\Scripts\python.exe -B -m tools.deploy_analysis --help
```

| Test file | Behavior covered |
|---|---|
| [test_simulator.py](../tests/test_simulator.py) | Correlated fault/recovery signals, timestamps, validation and retry batch identity |
| [test_rules.py](../tests/test_rules.py) | Exact thresholds/durations, all required signals, bad/gapped/stale/future data and recovery |
| [test_deploy.py](../tests/test_deploy.py) | Capacity, native init sidecars, taints/pressure, ownership, preserved placement and manifest parsing |
| [test_analysis.py](../tests/test_analysis.py) | SOP references, sticky severity, model selection, sources/evidence, busy/errors, origin rejection and SSE validation |
| [integration.sql](../tests/integration.sql) | Live hypertable/freshness, writer/reader permissions and duplicate-event rejection; rolls back probe writes |

The unit suite has 22 tests at the documented release. It does not contact real
models or prove answer quality. The live SQL check briefly locks the demo table
while checking duplicate counts; it is not a pure read-only query.

The deployment scripts use the Python standard library and subprocess CLIs.
`manifest_resources()` handles both a Kubernetes List and concatenated JSON
objects returned by multi-document `kubectl create --dry-run=client -o json`.
All kubectl calls use an explicit context and timeouts. Error reporting avoids
echoing submitted Secret payloads.

## 6. Changing SOPs, rules or equipment

### SOP wording or new document

1. Edit/add Markdown under `sops` and retain clear synthetic-training labels.
2. Use uppercase section IDs such as `## BEARING`; keep each body <=3,200 characters.
3. Give changed content a **new revision** in the catalog. Never replace bytes
   under an already published ID/revision.
4. Preserve any section referenced by active rules. A new arbitrary revision is
   not sufficient for changing rule-supporting SOPs: see the next section.
5. Run the focused document/rule tests, then the unit suite.
6. Rebuild only the app and deploy with placement preservation.
7. Verify new original checksums, index state/count, and retrieval before inference.

Changing the active package changes the content-addressed collection. Old
collections/originals/diagnosis records are retained; there is no automated garbage
collector. Do not delete the warranty assistant's collections.

### Thresholds, rule revisions or new equipment

Rule/source versioning currently targets **1.0**. `save_alert()` writes that
rule/source revision, and diagnosis requires the exact supporting revision in
the active passage package. Changing a rule-supporting SOP to 1.1 without
coordinating rule metadata/storage/passage availability can make existing or new
alerts non-diagnosable. There is no automatic rule-version migration or old-alert
passage reload.

For a versioned behavior change, update the rule definition, persisted revision
handling, catalog/package and affected tests together; decide explicitly how
existing alerts retain access to their original source revision.
Do not simply change a constant and claim historic reproducibility.

A new asset/channel similarly needs coordinated inventory/schema, simulator or
adapter, detector fields/rules, SOP, API/UI labels and focused tests.
`001-schema.sql` initializes only an empty volume: modifying it does not upgrade
live tables. Add a reviewed migration instead. The DB currently accepts only
running/good synthetic measurements; real-device state/quality handling is not a
drop-in adapter setting.

## 7. Image/deployment release behavior

One Dockerfile installs the same runtime dependencies for simulator and app.
The default image command starts the simulator; Kubernetes starts the app with
Uvicorn explicitly. Separate ACR repository/digest entries let each deployment
retain its existing image during component-only releases.

The initial builder produces the simulator and imports TimescaleDB. A second
`-AppOnly` build adds the app digest to `.local\images.json`. An app-only or
simulator-only build requires existing metadata for the same registry. The fixed
repository prefix is `ssrikantan/realtime-telemetry`; it is not an environment
variable or a CLI option.

Direct dependencies are pinned, but there is no full transitive lockfile, hashed
wheel set or digest-pinned Python base. Record deployed image digests for a
repeatable demo release; rebuilding later may produce different bytes even with
the same source. No claim of byte-for-byte reproducibility is made.
