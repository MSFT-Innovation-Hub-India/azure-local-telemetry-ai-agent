# Independent monitoring and diagnostic application

For a new environment, start with the [ordered deployment guide](DEPLOYMENT.md)
and [shared-service prerequisites](DEPENDENCIES.md). This page covers operating
the deployed demo. See [architecture](ARCHITECTURE.md) and the
[code guide](DEVELOPMENT.md) for implementation details.

## Two demos, independently deployed

| Demo | Kubernetes service | Local URL |
|---|---|---|
| Existing warranty AI assistant | `assistant-demo/assistant-web` | http://127.0.0.1:8080 |
| Equipment telemetry | `telemetry-demo/telemetry-web` | http://127.0.0.1:8090 |

These are separate applications, images, deployments and browser origins. Neither
UI embeds, proxies or routes to the other. Keep both tabs open; switching requires
no deployment, model loading or node-placement changes.

They share the already deployed embedding service, Qdrant and model endpoints.
That is shared infrastructure, not independent compute: simultaneous inference can
contend for CPU/model capacity. There is no cross-application global inference
queue. Telemetry permits one diagnosis at a time and returns HTTP 409 when busy.
The existing warranty app's concurrency mechanism is unchanged.

If the laptop tunnels need reopening, keep these in separate terminals while the
existing Arc proxy is active:

```powershell
$Context = "<target-kubectl-context>"
kubectl --context $Context -n assistant-demo port-forward svc/assistant-web --address 127.0.0.1 8080:80
```

In the other terminal, set the context there too:

```powershell
$Context = "<target-kubectl-context>"
kubectl --context $Context -n telemetry-demo port-forward svc/telemetry-web --address 127.0.0.1 8090:80
```

Port-forwarding is development access, not an appliance ingress or a disconnected
transport guarantee. Both apps and the simulator continue running without these
browser tunnels.

## Using the telemetry UI

1. Open the telemetry URL. Review equipment freshness, the evaluator and SOP index.
2. Select a chart parameter. The chart uses five-second averages over ten minutes;
   missing buckets produce visible gaps, not interpolated healthy readings.
3. Select an alert. Read the triggering evidence, potential impact, related
   parameters, missing observations and exact SOP revision/section.
4. Choose **qwen2.5-0.5b** or **qwen2.5-14b** in the diagnostic workspace. The default
   is 0.5B; your choice is remembered only for this app in browser local storage.
5. Click **Generate diagnosis**. No model is called merely by viewing the dashboard
   or generating an alert. Model calls can take several minutes; rules continue
   running independently. There is no automatic switch to another model.
6. Review the saved response, selected model, reported tokens, evidence snapshot
   and expandable source passages. Model text is advisory and may be incorrect;
   the deterministic rule remains the authority for severity.
7. Optionally acknowledge with a note. Acknowledgement does not resolve an alert.
   Resolution occurs only after the rule's sustained recovery condition. Include
   resolved alerts to review their event history and saved diagnoses.

The app starts monitoring when deployed; it does not fabricate historical alerts
from previous simulator cycles. Allow one cycle for live fault/recovery events.

### Model transport and verified results

The backend consumes authenticated, CA-verified OpenAI-compatible streaming
responses from the shared model endpoints. This avoids the existing model proxy's
60-second non-streaming response timeout without modifying that proxy or restarting
model workloads. The browser receives the completed, saved diagnosis, not live token
deltas. The backend applies a five-minute inference budget and rejects incomplete
streams, invalid token metadata and references to unknown source identifiers.

Single live bearing-alert requests after deployment produced:

| Model | Inference time | Result |
|---|---|---|
| 0.5B | 14.96 s | HTTP 200; saved with three sources, but invented relationships between measurements and omitted inline citations |
| 14B | 74.87 s | HTTP 200; saved with three sources and an explanation citing the bearing SOP, related parameters and uncertainty |

These are individual requests, not a benchmark or an accuracy certification.
**Prefer 14B for this demonstration.** Successful transport does not establish
diagnostic or operational correctness. The smaller model's answer
demonstrates why the rule evidence and original SOP must remain authoritative.

Neither endpoint reported token usage for these streamed requests; the UI
explicitly displays that counts were not reported rather than estimating them.
When an endpoint reports the output-limit finish reason, the application appends
a partial-output notice. A provider can still end a response mid-sentence without
reporting that reason; inspect the answer rather than treating a completed stream
as proof of a complete explanation.

Validation also passed all **22 unit tests**. During slow inference, telemetry
continued arriving and the detector heartbeat remained fresh. Alert history,
one-time acknowledgement, resolution and earlier diagnoses survived app upgrades.
All **67 other active pods**, including the telemetry database and simulator,
remained Ready with unchanged UIDs, nodes and restart counts. Both application
URLs were healthy after verification.

## SOPs, rules and document storage

All documents are fictional, visibly marked training-only, and unsuitable for
actual equipment operation:

- [SOP-PMP-001](../sops/SOP-PMP-001.md): running envelope, timestamps and data quality.
- [SOP-PMP-002](../sops/SOP-PMP-002.md): bearing/suction troubleshooting, exact
  thresholds, corroborating parameters, limits of diagnosis and possible impact.
- [SOP-PMP-003](../sops/SOP-PMP-003.md): inspection evidence, upkeep reviews and
  recovery-record responsibilities.

The [catalog](../sops/catalog.json) identifies immutable revisions. Originals are
stored in `analysis.sop_documents`; `analysis.sop_active` identifies current
revisions. Content changes without a new revision fail startup explicitly. The
current package contains **16 indexed sections** across three documents.

This uses PostgreSQL as the small versioned document store, not an additional
document-storage pod. Qdrant stores section text/metadata and vectors separately.
Collections are content-addressed with the exclusive `telemetry-sops-` prefix.
Index publication occurs only after all expected sections are embedded and
written. Existing warranty collections are never renamed, replaced or deleted.
The embedding model/revision must match the existing 384-dimensional MiniLM API.

Rules are machine-readable Python definitions in [rules.py](../telemetry/rules.py).
The detector is deliberately not dependent on an LLM:

| Family | Warning | Critical | Clear |
|---|---|---|---|
| Bearing | Temperature >=75 C AND vibration >=4 mm/s for 30 s | Temperature >=85 C AND vibration >=6 mm/s for 20 s | Temperature <=70 C AND vibration <=3 mm/s for 30 s |
| Suction | Pressure <=1 bar AND flow <=34 m3/h for 30 s | Pressure <=0.6 bar AND flow <=28 m3/h AND vibration >=4.5 mm/s for 20 s | Pressure >=1.2 bar AND flow >=38 m3/h for 30 s |
| Telemetry stale | Latest usable reading older than 15 s | Not used | Fresh continuous readings for 20 s |

A gap exceeding six seconds invalidates a continuous mechanical-rule window.
Non-good, non-running or future readings cannot satisfy those windows. Missing
data never resolves mechanical alerts. Critical severity stays attached to an
active incident until fully recovered. Recurrence creates a new incident.

The diagnostic orchestrator uses bounded, read-only telemetry queries and SOP
retrieval as tools. It does not execute LLM-generated SQL or equipment commands.
It supplies both trigger-time observations and current observations, labels missing
instrumentation, and includes the exact rule-supporting SOP section alongside
semantic retrieval. Simulator scenario labels are excluded from diagnostic
evidence. Every successful diagnosis is retained with its model and sources.

## Deployment and preservation boundary

The analysis deployment is separate from the foundation deployment. It does not
reapply database, simulator, model or warranty app pod templates.

Use the [initial analysis deployment commands](DEPLOYMENT.md#7-deploy-the-independent-analysis-application)
or [application-only upgrade commands](DEPLOYMENT.md#9-subsequent-releases-and-credential-maintenance).
Those examples define target variables, check native exit codes and verify
preservation. Do not copy the original lab's context into a new environment.

The new backend requests 200m CPU/384 MiB and is limited to 1 CPU/768 MiB. It stays
inside the existing namespace quota. The capacity guard counts existing workloads
and reserves the full new workload limit plus headroom. Subsequent upgrades must
use `--preserve-placement`, which refuses resource changes or moving the app.

[002-analysis.sql](../db/002-analysis.sql) is applied transactionally through the
owned database pod, without a database restart. It adds plain relational analysis
tables and a limited `telemetry_app` role; the role can read telemetry and persist
analysis, but cannot modify raw telemetry or create schema objects.

Approved writes:

- New app, Service, Secrets, ConfigMaps and additive NetworkPolicies in `telemetry-demo`.
- New schema/role in the owned telemetry database; no raw telemetry alteration.
- One new [shared-access policy](../deploy/shared-access.yaml) in `assistant-demo`,
  selecting only Qdrant/embedding pods and allowing only `telemetry-web` from
  `telemetry-demo` on their API ports. Existing policies are not edited.
- A new content-addressed telemetry SOP collection in the existing Qdrant instance.

Existing credentials/CA are copied in memory into the telemetry namespace. They
are not printed or saved locally. Reuse of the existing Qdrant API key is a lab
trust arrangement; collection naming is not authorization isolation. Use scoped
credentials or separate services for production tenant isolation.

## Health, errors and limitations

- `/healthz`: process health. `/readyz`: recent successful detector evaluation.
- `/api/overview`: assets, alerts, available models, document/index state and errors.
- SOP indexing failure is visible and retried; deterministic detection continues.
- Diagnosis failure returns HTTP 503; no fabricated answer or silent model fallback.
- Alert/acknowledgement/diagnosis records survive app replacement in PostgreSQL.
- Inference uses the existing CA and model API key; no TLS verification bypass.
- As with the foundation, ACR pull tokens expire. Refresh using the foundation
  deployer's `--refresh-pull-only` mode before image rescheduling if necessary.
- This is a localhost-accessed lab app, without end-user authentication or role
  separation. Do not expose it publicly. Same-origin mutation checks are not auth.
- There are no automatic external notifications, equipment actuation, maintenance
  work-order integration, database HA, backups or production ingress in this demo.
- Models are shared; avoiding pod restarts does not prove zero inference contention.
- A schema migration can briefly take normal database locks. It does not restart
  pods or move persistent volumes. The seeded document package currently targets
  rule/source revision 1.0; future rule revisions require an explicit release.

## Suggested ten-minute demonstration

The cycle is relative to **simulator process startup**, not opening the browser
or starting the analysis app. If you join mid-cycle, use the trends/history and
wait for the next recurrence; do not restart workloads merely to reset the show.

| Approximate cycle time | What to demonstrate |
|---|---|
| 0-2 min | Three fresh assets, healthy reference, parameter/unit choices and original SOP library |
| 2-5 min | Correlated fault ramp; warnings typically around minute 4 and critical around minute 5, after the sustained windows |
| 5-7 min | Bearing vs suction evidence, different related checks, missing independent observations and possible impact |
| 7-9 min | Partial recovery does not erase critical severity; acknowledgement does not clear an alert |
| Around 9 min | Sustained clear resolves the incidents; Include resolved retains evidence/events/diagnoses |
| 9-10 min | Healthy readings, retained history, then next-cycle recurrence with new incident IDs |

During the fault/incident walkthrough:

1. Select PUMP-001's bearing alert and compare heat/vibration with lubricant
   pressure, current and ambient conditions.
2. Select PUMP-002's suction alert and compare pressure/flow with discharge
   pressure, speed/current and the explicitly missing supply/strainer/valve data.
3. Generate one 14B explanation. Open its cited source and compare numeric values
   against the saved evidence, not readings that arrived a minute later.
4. Optionally compare 0.5B on the same alert. Explain its observed inaccuracies;
   do not present its output as a validated conclusion.
5. Acknowledge one active alert with an observation note. Show that it remains
   active until sustained recovery; after resolution, show the event history.
6. Switch to the separate warranty browser tab. No telemetry deployment, model
   reload or UI route switching is required. Avoid unnecessary simultaneous
   inference if you want to compare single-request latency.

## Read-only operational inspection

Use the target `$Context` from the deployment guide in your main terminal.
These commands expose workload metadata/logs, not Secret contents:

```powershell
kubectl --context $Context -n telemetry-demo get pods,pvc -o wide
kubectl --context $Context -n telemetry-demo get resourcequota telemetry-budget
kubectl --context $Context -n telemetry-demo logs deployment/pump-simulator --tail=20
kubectl --context $Context -n telemetry-demo logs deployment/telemetry-web --tail=40
kubectl --context $Context -n telemetry-demo logs timescaledb-0 --tail=30
kubectl --context $Context -n telemetry-demo get events --sort-by=.lastTimestamp
```

Inspect data and persistent analysis without fetching passwords:

```powershell
Get-Content -Raw .\db\inspect.sql |
    kubectl --context $Context -n telemetry-demo exec -i timescaledb-0 -- `
    psql -U postgres -d telemetry -f -

@'
\set ON_ERROR_STOP on
SELECT document_id, revision, sha256 FROM analysis.sop_documents ORDER BY document_id, revision;
SELECT collection_name, chunk_count, indexed_at FROM analysis.index_status;
SELECT equipment_id, rule_id, severity, opened_at, acknowledged_at, resolved_at
FROM analysis.alerts ORDER BY opened_at DESC LIMIT 10;
SELECT event_type, count(*) FROM analysis.alert_events GROUP BY event_type ORDER BY event_type;
SELECT model_id, elapsed_seconds, created_at, usage
FROM analysis.diagnoses ORDER BY created_at DESC LIMIT 10;
'@ | kubectl --context $Context -n telemetry-demo exec -i timescaledb-0 -- `
    psql -U postgres -d telemetry -f -
```

`postgres` over the local pod socket is administrative; these queries happen to
be read-only, but anyone with this exec capability can do more. For interactive
telemetry-only read access, the DB's existing reader environment can be used
without printing its password:

```powershell
kubectl --context $Context -n telemetry-demo exec -it timescaledb-0 -- `
    sh -c 'PGPASSWORD="$READER_PASSWORD" psql -h 127.0.0.1 -U telemetry_reader -d telemetry'
```

Do not dump Secrets to YAML, commit Azure CLI profiles or put database/model keys
in a browser or command argument. There is no automated backup procedure in this
demo. App replacement retains database records; that is persistence testing,
not proof that lost/deleted storage can be recovered.

## Troubleshooting by layer

| Symptom | Check / safe response |
|---|---|
| Azure CLI import/native module failure before proxy connection | Check `az --version`, bundled Python and the extension path in the traceback. Validate `az connectedk8s proxy --help` before cluster debugging. Repair only the implicated extension/ABI conflict using the intended supported version; an application venv cannot repair CLI-native modules. |
| Wrong cluster, Forbidden or API unreachable | Verify explicit context, proxy terminal, tenant/subscription and RBAC. Do not switch a global subscription or restart shared workloads as a guess. |
| No eligible worker | Check actual pool label, Ready/pressure/taints and allocated requests. Analysis hardcodes `slmnodepool`. Ask the platform owner for capacity; do not bypass the guard. |
| Unowned resource refusal | Inspect ownership and confirm the target. Never stamp ownership labels onto unrelated resources to force adoption. |
| ImagePullBackOff / unauthorized pull | Inspect pod events, registry reachability and token age; use the documented pull-only refresh. Running cached containers do not prove a future pull will succeed. |
| PVC Pending or mount failure | Inspect PVC/events and Azure Local CSI topology/capacity. Do not delete the PVC or change the shared StorageClass as a shortcut. |
| Database initialization failed | Inspect DB logs and initialization SQL. It runs only for an empty data directory. Restore original credentials if missing; do not regenerate them over existing data. |
| Simulator not Ready / no fresh readings | Inspect explicit connection errors, DB readiness, DNS and namespace policies. Successful commits update its heartbeat. Schema/permission errors need correction, not infinite retries. |
| App Ready but SOP index unavailable | Inspect overview index error and app logs. Check embedding response model/revision/dimensions, Qdrant API key, labels/ports and the additive ingress policy. Detector readiness is deliberately independent. |
| DNS Service exists but dependency requests fail | Check ready CoreDNS endpoints and allowed DNS pod labels. Check both source egress and destination ingress. Do not rewrite shared DNS/CNI configuration blindly. |
| Model missing or catalog rejected | Both exact deployment IDs and expected URLs must be present, with matching keys and CA. A single-model or three-model catalog is currently unsupported. |
| TLS failure / HTTP 401 or 403 from a model | Verify trusted Service DNS certificate and copied CA/API key; follow controlled shared-credential rotation. Never add `--insecure` or disable verification. |
| Model HTTP 504 or malformed/incomplete stream | Confirm the current streaming-capable app image and endpoint protocol, then inspect app and read-only model logs with the service owner. Do not modify/restart the shared model proxy just to hide a timeout. |
| HTTP 409 during diagnosis | A request is already in progress. Wait for completion; do not launch parallel retries or assume automatic model fallback. |
| No token counts | Expected if the model stream omitted usage. The UI explicitly reports missing counts; do not estimate or treat null as zero. |
| Answer invents facts, units or parameter relationships | Compare saved evidence and source passages; prefer 14B. Neither a source list nor HTTP 200 proves a grounded answer. Severity is controlled by deterministic rules. |
| No active alerts | The equipment may be healthy/recovering. Enable Include resolved, check detector freshness and allow a full cycle. The app does not replay every historic simulator cycle into incidents. |
| Critical incident persists while values improve | Intended hysteresis: severity remains critical until the full clear window, not merely below critical thresholds. Latest evidence can show warning-level recovery. |
| Acknowledgement does not remove an alert | Intended: it records review only. A second acknowledgement is idempotent. Resolution is driven by fresh sustained clear conditions. |
| SOP content changed without new revision | Publish a new immutable revision. Rule-supporting revision changes require coordinated code/history migration; see the code guide. |
| UI tunnel exits after upgrade | The selected pod was replaced. Reopen only the telemetry Service port-forward, leaving the warranty tunnel alone. |
| Baseline comparison reports an unrelated pod change | Investigate named pod/controller events and independent cluster activity. Do not automatically delete, redeploy or roll back unrelated workloads. |

## Stopping and resuming

Ctrl+C in a port-forward terminal closes only that browser tunnel; Ctrl+C in the
proxy terminal ends connected cluster access. Neither action stops the simulator,
DB or detector on the appliance. Keep an existing warranty connection running
when stopping only the telemetry browser.

To resume: establish the approved cluster access, refresh pull credentials if a
rollout/reschedule is planned, reopen the appropriate Service tunnel, and check
freshness/index readiness. There is no need to rebuild, redeploy or restart models
just to reopen a browser. Use approved maintenance procedures for actual workload
shutdown or data removal; the demo intentionally provides no destructive reset.
