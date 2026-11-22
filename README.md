# Equipment telemetry AI agent on Azure Local

[Project overview](https://msft-innovation-hub-india.github.io/azure-local-telemetry-ai-agent/) |
[Source code](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent)

A reproducible demonstration of live, fictional pump telemetry, deterministic
condition alerts and SOP-grounded AI explanations on an existing Azure Local
Arc-enabled Kubernetes cluster.

The telemetry dashboard and the warranty AI assistant are **separate applications**.
You can keep both open. They share existing model, embedding and Qdrant services,
not a combined UI or deployment.

> All equipment, telemetry and SOPs are fictional training material. This is not
> an equipment protection system, a validated physical model or manufacturer
> guidance. AI explanations are advisory; deterministic rules determine alerts.

## Documentation: start here

| Document | What it covers |
|---|---|
| [Deployment guide](docs/DEPLOYMENT.md) | Ordered, parameterized PowerShell commands for another environment: access, sign-in isolation, builds, preflight, deployment, validation and upgrades |
| [Shared-service prerequisites](docs/DEPENDENCIES.md) | Exact external contracts, optional DNS Service setup, and fresh-lab setup using the companion project |
| [Architecture and design](docs/ARCHITECTURE.md) | Components, pods and containers on the cluster (what each does, including sidecars), data/request flows, database model, rules, RAG, security, capacity and design trade-offs |
| [Code and extension guide](docs/DEVELOPMENT.md) | File/function map, configuration, APIs, tests, SOP/rule authoring and limitations when adapting the code |
| [Demo and operations runbook](docs/ANALYSIS.md) | UI walkthrough, bringing the demo up with `tools\start-demo.ps1`, demo narrative and talk track, both models, operating procedures, troubleshooting and measured validation results |

**For a new environment:** follow the deployment guide from the beginning. Do not
apply the YAML files directly: they contain placeholders, and the deployers perform
ownership, placement, capacity, credential and migration checks.

The full AI demonstration is not self-contained infrastructure provisioning.
This project deploys TimescaleDB, the simulator and the telemetry app. The cluster,
storage driver, Foundry Local models, embedding API and Qdrant must first satisfy
the [documented prerequisites](docs/DEPENDENCIES.md). Azure IoT Operations, MQTT,
Azure IoT Hub and Azure-hosted database services are **not required**.

## What runs

```text
Three simulated pumps --current UTC samples--> TimescaleDB + 20 GiB PVC
                                                  |
                              five-second deterministic evaluation
                                                  |
                                     persistent alerts and history
                                                  |
Browser --> independent telemetry app --> telemetry evidence + original SOPs
                                      --> shared MiniLM embeddings / Qdrant
                                      --> selected local Qwen 0.5B or 14B
                                                  |
                                      saved advisory diagnosis
```

- Correlated readings every approximately two seconds for three pump skids.
- Ten-minute cycle: healthy, fault ramp, sustained fault, recovery, healthy.
- Bearing, suction and telemetry-staleness alerts with sustained windows.
- Three synthetic SOPs, 16 indexed sections, immutable originals in PostgreSQL.
- An isolated, content-addressed Qdrant collection; warranty collections untouched.
- Live assets, parameter trends, evidence, impact, related checks and missing data.
- Explicit model choice, acknowledgements, recovery history and saved diagnoses.
- TLS-verified, authenticated local inference; no external hosted LLM API.

TimescaleDB is PostgreSQL extended by **Timescale/Tiger Data**, not a
Microsoft-provided database container (see
[why TimescaleDB rather than a plain indexed table](docs/ARCHITECTURE.md#why-timescaledb-instead-of-a-plain-indexed-table)). Its pinned upstream image is mirrored to
your approved ACR. Review the [upstream instructions](https://github.com/timescale/timescaledb-docker)
and [license](https://github.com/timescale/timescaledb/blob/main/LICENSE) before
redistribution or production use.

## Companion project: the warranty PDF assistant

The second demonstration, and the shared AI services this project builds on, come
from a separate repository:
**[azure-local-rag-assistant](https://github.com/MSFT-Innovation-Hub-India/azure-local-rag-assistant)**
(previously linked here as `Azure-Local-Samples-101`). It is a React/FastAPI PDF
assistant with a local embedding service, a Qdrant vector database and a selectable
Qwen model, deployed to the same cluster in the `assistant-demo` namespace and
opened at http://127.0.0.1:8080. Its **Contoso Field Service** scenario answers
questions about warranty policy, India/EMEA/APAC regional addenda and goodwill
approval limits from indexed PDFs, and cites the passages it used. Further
scenarios (operations, manufacturing, retail) are packaged as content only: a
`scenario.json`, a system prompt and PDFs.

### What this project reuses from it

This project does **not** use the assistant's application, UI, scenarios, PDFs or
prompts. It reuses the services the assistant deployed:

| Shared piece | Provided by the companion repository | How the telemetry app uses it |
|---|---|---|
| Qdrant vector database (`qdrant`, port 6333, API-key auth) | Stores the assistant's PDF-passage collections | Creates its own isolated, content-addressed collection `telemetry-sops-<hash>` for the 16 SOP sections and queries only that prefix; warranty collections are never read or written |
| Embedding service (`embeddings`, `POST /embed`, MiniLM `all-MiniLM-L6-v2`, 384 dimensions) | Turns PDF text into vectors | Embeds the SOP sections at startup and the alert text at diagnosis time; rejects a response whose model, revision or dimensions differ |
| Model catalog and credentials (`assistant-models` ConfigMap, `assistant-credentials` Secret) | Lists the Qwen models and holds the Qdrant and model keys | The deployer copies only the selected keys, the model list and the model CA into this project's own `telemetry-demo` Secret and ConfigMaps; the source objects are not modified |
| Qwen2.5 0.5B and 14B models (Foundry Local) | Its `deploy/qwen2.5-*.yaml` manifests create the two model deployments in the fresh-lab path | Calls the same endpoints with the same keys and CA, only when a diagnosis is requested |
| `assistant-demo` namespace and network | Isolates the assistant's pods | One additional NetworkPolicy ([deploy/shared-access.yaml](deploy/shared-access.yaml)) lets only `telemetry-web` reach Qdrant and the embeddings service |

The two applications share infrastructure, not a UI, conversation or deployment, so
using both at once can contend for embedding and model capacity. There is no global
queue; the telemetry app allows one diagnosis at a time. The assistant calls the model
without streaming and shows token counts; the telemetry app streams for the 14B model
and cannot show them (see
[model transport and token counts](docs/ANALYSIS.md#model-transport-response-modes-and-token-counts)).

To reuse an existing assistant stack, follow the
[prerequisite contracts](docs/DEPENDENCIES.md#1-what-must-already-exist). To build the
shared stack from scratch, use the companion repository's own runbook and the
[fresh-lab path](docs/DEPENDENCIES.md#5-fresh-lab-builddeploy-the-companion-shared-stack).
For what each of its pods and containers does, see
[pods and containers on the cluster](docs/ARCHITECTURE.md#pods-and-containers-on-the-cluster).

## Current demonstration

| Application | Local browser URL |
|---|---|
| Telemetry agent | http://127.0.0.1:8090 |
| Existing warranty assistant | http://127.0.0.1:8080 |

These URLs require the Arc connection and separate port-forwards described in
the [deployment guide](docs/DEPLOYMENT.md#8-open-the-independent-applications).
The Kubernetes workloads continue running when the browser tunnels stop.

Verified on **November 13, 2026**:

- TimescaleDB 2.32.0 on PostgreSQL 17, a real hypertable and persistent CSI volume.
- Live ingestion, duplicate rejection, least-privilege writer and persistence.
- Warning, critical escalation, acknowledgement and sustained recovery.
- Three SOPs indexed; diagnoses saved with model identity, evidence and sources.
- Both models returned HTTP 200: 0.5B took 14.96 s; 14B took 74.87 s.
  These were individual requests, not a benchmark.
- **Prefer 14B:** the 0.5B explanation invented relationships between measurements.
- All 22 unit tests passed. All 67 other active pods retained their identities,
  placement and restart counts during the final analysis deployment checks.

## Preservation and lab boundaries

Deployments do not scale infrastructure or reapply existing model, embedding,
Qdrant or warranty application pod templates. Upgrades require
`--preserve-placement`, and changes to existing resource requests/limits are
refused. One additional, narrow NetworkPolicy in the shared-service namespace is
the explicitly documented exception to namespace isolation.

Shared services still share compute: concurrent demonstrations can contend.
The database and application are single replica. The demo has no end-user auth,
database TLS, backups/HA, external alert delivery or equipment control.
Image-pull tokens are short-lived. See the architecture and operations guides
before exposing or adapting the solution.

## Public project page

GitHub Pages publishes the project overview from `docs/index.md`, using the
`main` branch's `/docs` folder. `docs/_config.yml` configures the Cayman theme,
SEO metadata and generated sitemap; `docs/robots.txt` advertises the sitemap.
The page is crawlable, but search engines decide whether and when to index it.
