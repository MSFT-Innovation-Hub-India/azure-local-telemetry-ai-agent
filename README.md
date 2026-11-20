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
| [Architecture and design](docs/ARCHITECTURE.md) | Components, data/request flows, database model, rules, RAG, security, capacity and design trade-offs |
| [Code and extension guide](docs/DEVELOPMENT.md) | File/function map, configuration, APIs, tests, SOP/rule authoring and limitations when adapting the code |
| [Demo and operations runbook](docs/ANALYSIS.md) | UI walkthrough, both models, operating procedures, troubleshooting and measured validation results |

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
Microsoft-provided database container. Its pinned upstream image is mirrored to
your approved ACR. Review the [upstream instructions](https://github.com/timescale/timescaledb-docker)
and [license](https://github.com/timescale/timescaledb/blob/main/LICENSE) before
redistribution or production use.

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
