# Solution architecture diagrams (inside the Kubernetes cluster)

These diagrams show only what runs **inside the Arc-enabled Kubernetes cluster**.
Azure-side pieces (Arc, ACR, Entra) are outside the scope except where they touch
a pod. For the prose, see [ARCHITECTURE.md](ARCHITECTURE.md); for commands, see
[DEPLOYMENT.md](DEPLOYMENT.md).

| Part | Diagram |
|---|---|
| Telemetry analysis (this repo) | [1. Pods and services](#1-telemetry-analysis-pods-services-and-storage), [2. Runtime flows](#2-telemetry-analysis-runtime-flows), [3. SOP indexing pipeline](#3-telemetry-analysis-sop-indexing-pipeline) |
| Shared services | [4. How the common services are hosted](#4-shared-services-how-they-are-hosted) |
| PDF assistant (companion repo) | [5. Pods and services](#5-pdf-assistant-pods-services-and-storage), [6. Document ingestion pipeline](#6-pdf-assistant-document-ingestion-pipeline), [7. Question runtime](#7-pdf-assistant-question-runtime) |

**Terminology used in this solution**

| You may say | In this solution |
|---|---|
| Dataset generator | `pump-simulator` Deployment (`python -m telemetry.simulator`) |
| Database | TimescaleDB (PostgreSQL 17 + Timescale extension) in `timescaledb-0` |
| Model | Qwen2.5 0.5B or 14B on CPU, served by Foundry Local |
| Model API | HTTPS `/v1/chat/completions` behind an `nginx-sidecar` in each model pod |
| UI | **Telemetry app: plain HTML/CSS/JavaScript** in `static/`, served by FastAPI (no React). **PDF assistant: React**, built into its FastAPI image |
| Vector database | Qdrant, `qdrant-0` StatefulSet |
| Embedding service | MiniLM (`all-MiniLM-L6-v2`, 384 dimensions) running with FastEmbed/ONNX in the `embeddings` Deployment |
| Chunking | Plain Python code inside the app or indexer process. Neither Qdrant nor MiniLM chunks |

---

## 1. Telemetry analysis: pods, services and storage

```mermaid
flowchart LR
    user["Operator browser<br/>localhost:8090"]

    subgraph cluster["Azure Local: Arc-enabled Kubernetes cluster"]
        subgraph tdemo["Namespace telemetry-demo (owned by this solution)"]
            tsvc["Service telemetry-web<br/>port 80 to 8000"]
            subgraph webpod["Pod telemetry-web-* (Deployment, 1 replica)"]
                direction TB
                api["FastAPI on uvicorn, 1 worker<br/>REST API + static UI files<br/>(vanilla JavaScript, no React)"]
                det["Detector thread<br/>rules every 5 s"]
                idx["SOP indexer thread<br/>chunk, embed, upsert at startup"]
            end
            simpod["Pod pump-simulator-* (Deployment)<br/>dataset generator<br/>3 pumps, a row each about 2 s"]
            dbsvc["Service timescaledb<br/>port 5432"]
            dbpod["Pod timescaledb-0 (StatefulSet)<br/>PostgreSQL 17 + TimescaleDB"]
            pvc[("PVC 20 GiB<br/>azlocal.csi.azure.com")]
            cfg["Secrets and ConfigMaps<br/>DB passwords, copied Qdrant and model keys,<br/>model catalog, model CA"]
        end

        subgraph adm["Namespace assistant-demo (shared services)"]
            embsvc["Service embeddings :8001"]
            emb["Pod embeddings-*<br/>MiniLM via FastEmbed (ONNX)"]
            qsvc["Service qdrant :6333"]
            qd["Pod qdrant-0<br/>collection telemetry-sops-hash"]
            qpvc[("PVC qdrant-data 5 GiB")]
        end

        subgraph fdm["Namespace foundry-local-operator (shared models)"]
            msvc["Model Services<br/>HTTPS 5000 to pod 8443"]
            m05["Pod Qwen2.5 0.5B<br/>inference + nginx-sidecar"]
            m14["Pod Qwen2.5 14B<br/>inference + nginx-sidecar"]
        end
    end

    user -->|"Arc proxy and kubectl port-forward"| tsvc
    tsvc --> api
    simpod -->|"INSERT as telemetry_writer"| dbsvc
    api -->|"SELECT telemetry, read/write analysis as telemetry_app"| dbsvc
    det -->|"evaluate rules, write alerts"| dbsvc
    dbsvc --> dbpod
    dbpod --- pvc
    cfg -.->|"mounted at /run/credentials, /run/models, /run/trust"| webpod
    cfg -.->|"writer password"| simpod
    idx -->|"POST /embed"| embsvc
    idx -->|"create collection, upsert"| qsvc
    api -->|"embed alert text"| embsvc
    api -->|"vector search"| qsvc
    embsvc --> emb
    qsvc --> qd
    qd --- qpvc
    api -->|"HTTPS, API key, SSE or JSON"| msvc
    msvc --> m05
    msvc --> m14
```

Key points:

- **One image, two roles.** The simulator and the web app are built from the same
  image; only the command differs (`telemetry.simulator` vs `uvicorn telemetry.app:app`).
- **Three pods owned here**, each `1/1` with no sidecars. Everything else is reused.
- **Database access is least-privilege**: the simulator can only insert samples; the
  app can read telemetry and read/write analysis tables.
- **Network access is explicit.** `telemetry-private-network` limits the namespace;
  `telemetry-analysis-access` allows `telemetry-web` egress to Qdrant (6333),
  embeddings (8001) and the two model pods (8443). One additive policy in
  `assistant-demo` ([shared-access.yaml](../deploy/shared-access.yaml)) admits that
  traffic on the receiving side.
- **No ingress.** Access to the browser UI is through a port-forward over the Arc
  connection.

---

## 2. Telemetry analysis: runtime flows

Three separate flows run at runtime. Only the third involves an LLM.

### 2a. Continuous: ingestion and deterministic detection (no AI)

```mermaid
flowchart LR
    sim["pump-simulator<br/>600 s fault cycle<br/>PUMP-001 bearing fault<br/>PUMP-002 suction fault<br/>PUMP-003 healthy"]
    ts[("telemetry.samples<br/>hypertable, daily chunks<br/>7-day retention")]
    latest["telemetry.latest"]
    det["Detector thread in telemetry-web<br/>every 5 s: rules over sustained windows"]
    alerts[("analysis.alerts<br/>analysis.alert_events")]
    ui["Browser UI<br/>polls the REST API"]

    sim -->|"3 rows per batch, ON CONFLICT DO NOTHING"| ts
    ts --> latest
    ts -->|"time_bucket and window queries"| det
    det -->|"open, escalate, resolve"| alerts
    ui -->|"GET /api/overview, /api/trends, /api/rules/monitor, /api/data/*"| ts
    ui -->|"GET /api/overview, /api/alerts/id"| alerts
    ui -->|"POST /api/alerts/id/acknowledge"| alerts
```

### 2b. On request: diagnosis (retrieval plus a local LLM)

```mermaid
sequenceDiagram
    actor User
    participant UI as Browser UI (static JS)
    participant App as telemetry-web (FastAPI)
    participant DB as timescaledb-0
    participant Emb as embeddings Service
    participant QD as qdrant Service
    participant LLM as Qwen model pod (0.5B or 14B)

    User->>UI: Select alert and model, click Generate diagnosis
    UI->>App: POST /api/alerts/id/diagnose
    App->>App: Validate model and index status, take non-blocking lock
    App->>DB: Read the alert and the last 90 s of telemetry
    App->>App: Build evidence, related parameters and missing checks
    App->>Emb: POST /embed with the alert text
    Emb-->>App: 384-d vector (model and revision verified)
    App->>QD: Search collection telemetry-sops-hash, top 4 passages
    QD-->>App: SOP section passages with scores
    App->>App: Rule-supporting passage plus up to 2 distinct retrieved passages
    App->>LLM: HTTPS /v1/chat/completions, temperature 0, API key, verified TLS
    LLM-->>App: JSON (0.5B) or SSE stream (14B)
    App->>App: Validate finish reason and source references
    App->>DB: Save answer, model, sources, evidence and exchange
    App-->>UI: Completed saved diagnosis
```

A second request while one is running gets HTTP 409. The model cannot run SQL,
acknowledge alerts or change severity.

---

## 3. Telemetry analysis: SOP indexing pipeline

This is the telemetry app's version of "document upload". It is **not** a Job and has
no upload step: the SOP Markdown ships inside the app image, and an indexer thread
inside `telemetry-web` publishes it at startup.

```mermaid
flowchart TD
    img["SOP Markdown + catalog.json<br/>baked into the telemetry-web image (/app/sops)"]

    subgraph pod["Pod telemetry-web: SOP indexer thread (Python)"]
        direction TB
        load["1. Load catalog and originals<br/>verify SHA-256 against ID and revision"]
        store["2. Store originals and active pointers<br/>in one transaction"]
        chunk["3. Chunk by heading<br/>one passage per uppercase SECTION-ID heading (level 2),<br/>max 3,200 chars (16 passages from 3 SOPs)"]
        digest["4. Package digest over ordered IDs, revisions and checksums"]
        batch["5. Embed in batches of 8"]
        upsert["6. Upsert points with wait=true<br/>then verify the point count"]
        publish["7. Publish index status"]
        load --> store --> chunk --> digest --> batch --> upsert --> publish
    end

    pg[("TimescaleDB<br/>analysis.sop_documents<br/>analysis.sop_active<br/>analysis.index_status")]
    emb["embeddings Service :8001<br/>POST /embed<br/>MiniLM, 384 dimensions"]
    qd[("Qdrant :6333<br/>collection telemetry-sops-first-24-digest-chars<br/>cosine, UUID5 point IDs")]

    img --> load
    store --> pg
    batch -->|"texts"| emb
    emb -->|"vectors"| batch
    upsert -->|"vectors + passage text + section ID"| qd
    publish --> pg
    fail["Dependency down?<br/>retry every 60 s<br/>alerts keep working, diagnosis disabled"]
    batch -.-> fail
    upsert -.-> fail
```

Changed SOP content with an unchanged revision fails loudly. A new revision produces
a new digest, hence a new collection. Old collections are not deleted automatically.

---

## 4. Shared services: how they are hosted

These run in `assistant-demo` and `foundry-local-operator`. They come from the
[companion repository](https://github.com/MSFT-Innovation-Hub-India/azure-local-rag-assistant).
The telemetry app and the PDF assistant both consume them.

```mermaid
flowchart TB
    subgraph asst["Namespace assistant-demo"]
        direction TB
        subgraph embdep["Deployment embeddings (1 replica, Recreate)"]
            embsvc["Service embeddings :8001"]
            embpod["Pod embeddings-*<br/>container embeddings<br/>MiniLM ONNX baked into the image at /models<br/>FastEmbed + ONNX Runtime<br/>1 GiB memory, up to 2 CPU"]
            embsvc --> embpod
        end
        subgraph qdset["StatefulSet qdrant (1 replica)"]
            qsvc["Service qdrant :6333"]
            qpod["Pod qdrant-0<br/>container qdrant<br/>API key from Secret<br/>512 MiB memory"]
            qpvc[("PVC qdrant-data<br/>5 GiB, Azure Local CSI<br/>/qdrant/storage")]
            qsvc --> qpod --- qpvc
        end
        pyproc["Chunking = Python code<br/>NOT a separate service<br/>runs inside the indexer Job (PDFs)<br/>or the telemetry-web thread (SOPs)"]
    end

    subgraph fdm["Namespace foundry-local-operator (platform-owned)"]
        direction TB
        gw["Internal gateway (Istio / Envoy) and Services"]
        subgraph mp["Pod Qwen2.5 0.5B or 14B (CPU)"]
            ng["nginx-sidecar<br/>terminates TLS"]
            inf["inference container<br/>ONNX GenAI on CPU"]
            otel["otel-sidecar (native sidecar)"]
            pull["model-store-pull (init, exits)"]
            ng --> inf
        end
        store["Model store registry pod<br/>model artifacts"]
        op["inference-operator<br/>creates model Deployments"]
        gw --> ng
        pull -.->|"download model files at start"| store
        op -.->|"reconciles"| mp
    end

    apps["Clients:<br/>telemetry-web, assistant-web, indexer Job"]
    apps -->|"HTTP POST /embed"| embsvc
    apps -->|"HTTP + API key"| qsvc
    apps -->|"HTTPS + API key + trusted CA"| gw
    pyproc -.->|"calls"| embsvc
    pyproc -.->|"writes"| qsvc
```

| Service | Hosted as | Storage | Reached by | Controls |
|---|---|---|---|---|
| Qdrant | StatefulSet, 1 pod | 5 GiB CSI PVC | `qdrant.assistant-demo:6333` | API key in a Secret, NetworkPolicy, no TLS |
| Embedding service | Deployment, 1 pod, stateless | None; model baked into image | `embeddings.assistant-demo:8001` `POST /embed` | NetworkPolicy, no auth, no TLS |
| Chunking | Python library code in the caller | None | In-process | N/A |
| Qwen models | Foundry Local operator creates one Deployment per model | Model files pulled into the pod at start | HTTPS Service port 5000 to pod port 8443 | API key, TLS with a trusted CA |

---

## 5. PDF assistant: pods, services and storage

The PDF assistant is deployed from the companion repository into `assistant-demo`.
Source details are in its [ARCHITECTURE.md](https://github.com/MSFT-Innovation-Hub-India/azure-local-rag-assistant/blob/main/ARCHITECTURE.md)
and [deploy/stack.yaml](https://github.com/MSFT-Innovation-Hub-India/azure-local-rag-assistant/blob/main/deploy/stack.yaml).

```mermaid
flowchart LR
    user["Browser<br/>localhost:8080"]

    subgraph cluster["Azure Local: Arc-enabled Kubernetes cluster"]
        subgraph adm["Namespace assistant-demo"]
            wsvc["Service assistant-web<br/>port 80 to 8000"]
            subgraph webpod["Pod assistant-web-* (Deployment)"]
                react["React UI<br/>built into the image,<br/>served by FastAPI"]
                fapi["FastAPI backend<br/>session cookie, CSRF, scenarios,<br/>retrieval and Qwen client"]
                react --- fapi
            end
            embsvc["Service embeddings :8001"]
            emb["Pod embeddings-*<br/>MiniLM via FastEmbed"]
            qsvc["Service qdrant :6333"]
            qd["Pod qdrant-0<br/>vectors, passage text,<br/>metadata, scenario catalog"]
            qpvc[("PVC qdrant-data 5 GiB")]
            docs["Pod documents-*<br/>runs 'sleep' to mount the PDF volume"]
            dpvc[("PVC pdf-documents 2 GiB")]
            job["Job pdf-index-*<br/>container indexer<br/>runs on the same node as documents"]
            sec["Secret assistant-credentials<br/>ConfigMaps assistant-models, model-trust"]
        end
        subgraph fdm["Namespace foundry-local-operator"]
            msvc["Model Services"]
            m05["Qwen2.5 0.5B pod"]
            m14["Qwen2.5 14B pod"]
        end
    end

    user -->|"Arc proxy and port-forward"| wsvc
    wsvc --> react
    fapi -->|"embed question"| embsvc
    fapi -->|"search passages"| qsvc
    fapi -->|"HTTPS chat completion"| msvc
    embsvc --> emb
    qsvc --> qd --- qpvc
    msvc --> m05
    msvc --> m14
    docs --- dpvc
    job -.->|"read-only mount"| dpvc
    job -->|"embed chunks"| embsvc
    job -->|"write snapshot, publish"| qsvc
    sec -.-> webpod
    sec -.->|"Qdrant key only"| job
```

The web pod does **not** mount the PDF volume. It answers from the passages, text and
metadata stored in Qdrant, so the PDFs are needed only at indexing time.

---

## 6. PDF assistant: document ingestion pipeline

This runs **when a content release is published**, not on each question.

```mermaid
flowchart TD
    subgraph ws["Operator workstation"]
        pkg["tools.scenario package<br/>definition + prompt + all PDFs (ZIP)"]
        dep["tools.scenario deploy<br/>validate, check ownership and capacity,<br/>take publication lock"]
        pkg --> dep
    end

    subgraph cluster["Cluster: namespace assistant-demo"]
        docs["Pod documents-*<br/>(kubectl copy target)"]
        dpvc[("PVC pdf-documents 2 GiB<br/>PDFs and scenario ZIPs")]

        subgraph jobpod["Job pdf-index-* container indexer (Python)<br/>python -m assistant.indexer --folder /documents"]
            direction TB
            fp["1. Fingerprint PDFs<br/>unchanged = reuse existing snapshot"]
            ext["2. Extract with pypdf<br/>page by page, no OCR<br/>reject encrypted, corrupt, textless"]
            norm["3. Normalize whitespace"]
            chk["4. Chunk by characters<br/>window 900, overlap 120 (advance 780)<br/>never crosses pages<br/>keep file, page, chunk no., hash"]
            bat["5. Embed each chunk"]
            wr["6. Create new Qdrant collection (snapshot)<br/>and upsert vectors + text + metadata"]
            pub["7. Publish<br/>one catalog record makes prompt,<br/>revision and collection visible together"]
            fp --> ext --> norm --> chk --> bat --> wr --> pub
        end

        emb["embeddings Service :8001<br/>MiniLM, 384-d vectors"]
        qd[("Qdrant :6333<br/>new immutable collection<br/>+ scenario catalog<br/>PVC qdrant-data 5 GiB")]
    end

    dep -->|"kubectl upload"| docs
    docs --- dpvc
    dpvc -->|"read-only mount"| fp
    bat -->|"POST /embed"| emb
    emb -->|"384-d vectors"| bat
    wr --> qd
    pub --> qd
    fail["Failure: Job exits, no publication<br/>previous scenario stays searchable"]
    wr -.-> fail
```

| Step | Where it runs | Component |
|---|---|---|
| Upload | Operator workstation to `documents` pod | `kubectl` over the Arc connection |
| Extraction, chunking, orchestration | One-off `pdf-index-*` pod (`indexer` container) | Python: `pypdf` plus the `extract_chunks` function |
| Embeddings | `embeddings` pod | MiniLM via FastEmbed/ONNX |
| Vector storage | `qdrant-0` pod | Qdrant on a 5 GiB CSI volume |
| Scheduling constraint | Indexer pod affinity | Must land on the node where `documents` runs, because the 2 GiB volume is ReadWriteOnce |

Indexing is a one-off Job (`backoffLimit: 0`, 30-minute deadline). Finished pods show
`0/1 Completed`; that is normal. It is not incremental: any changed or removed PDF
triggers a complete new snapshot for that scenario.

---

## 7. PDF assistant: question runtime

```mermaid
sequenceDiagram
    actor User
    participant UI as React UI
    participant App as assistant-web (FastAPI)
    participant Emb as embeddings Service
    participant QD as qdrant Service
    participant LLM as Qwen model pod

    User->>UI: Pick scenario and model, ask a question
    UI->>App: POST /api/chat (question, scenario, model, CSRF token)
    App->>App: Validate request and session, resolve published snapshot, take lock
    App->>App: Use bounded history to resolve follow-ups
    App->>Emb: POST /embed with the retrieval question
    Emb-->>App: 384-d vector
    App->>QD: Search the scenario collection, up to 4 passages above threshold
    QD-->>App: Passages with file and page
    alt No evidence found
        App-->>UI: Explicit unsupported answer (Qwen is not called)
    else Evidence found
        App->>LLM: Authenticated TLS request with instructions, history, excerpts, question
        LLM-->>App: Completion and token usage
        App-->>UI: Answer, page citations, usage and model exchange
    end
```

---

## Notes and caveats

- **UI technology.** The telemetry UI in [static/](../static) is vanilla JavaScript.
  Only the PDF assistant uses React.
- **Sections 4 to 7 describe the companion repository** as documented on its `main`
  branch at the time of writing. If its manifests change, treat its repository as the
  source of truth.
- **Shared services do not isolate tenants.** Collection naming
  (`telemetry-sops-*` vs scenario collections) is logical separation, not
  authorization. Both apps use the same Qdrant API key.
- **Single replicas everywhere.** The database, the apps, Qdrant and the embedding
  service each run one replica. Both apps allow one generation at a time.
