---
layout: default
title: Real-Time Equipment Telemetry and AI Diagnostics on Azure Local
description: Explore an Azure Local equipment monitoring demo with TimescaleDB, rule-based pump alerts, and retrieval-augmented AI explanations grounded in SOPs using Foundry Local Qwen models.
permalink: /
---

# Real-time equipment telemetry and AI diagnostics on Azure Local

**Monitor simulated pumps, detect sustained equipment conditions, and explain
alerts with local AI grounded in standard operating procedures (SOPs).**

The **Azure Local Telemetry AI Agent** demonstrates an equipment condition
monitoring workflow on an existing **Azure Local, Azure Arc-enabled Kubernetes**
cluster. It combines live time-series data in **TimescaleDB**, deterministic
condition alerts, and **retrieval-augmented generation (RAG)** using local
**Foundry Local Qwen models**, **MiniLM embeddings**, and **Qdrant**.

[View the source code](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent) |
[Deploy the demo](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/DEPLOYMENT.md) |
[Explore the architecture](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/ARCHITECTURE.md)

> This is a demonstration using fictional equipment, telemetry, and SOPs.
> It is not a production equipment protection system or manufacturer guidance.
> Deterministic rules determine alerts; AI explanations are advisory.

## What the demonstration shows

- **Live equipment monitoring:** three simulated pump skids produce correlated
  readings approximately every two seconds, including temperature, vibration,
  pressure, flow, speed, and motor current.
- **Persistent time-series evidence:** TimescaleDB on PostgreSQL stores readings
  in a hypertable backed by an Azure Local CSI persistent volume.
- **Rule-based condition alerts:** bearing, suction, and telemetry-staleness
  checks use sustained windows, warning and critical states, acknowledgements,
  and recovery history.
- **SOP-grounded AI diagnostics:** the application retrieves relevant procedure
  passages and asks a selected local model to explain an alert using telemetry
  evidence and those sources.
- **Operator-facing evidence:** a live dashboard presents assets, parameter
  trends, impact, related checks, missing data, and saved diagnoses.
- **Local model choice:** operators can select Qwen2.5 0.5B or 14B through shared
  Foundry Local model services without an external hosted LLM API.

## Why this architecture matters

The demonstration separates **condition detection** from **AI interpretation**.
Rules decide when a condition becomes an alert; the language model explains the
available evidence rather than controlling equipment or deciding alarm state.

SOP originals remain in PostgreSQL, while Qdrant holds a derivative retrieval
index in an isolated collection. Saved diagnoses retain model identity, evidence,
and sources so an operator can revisit the explanation.

Inference, embedding, vector search, simulation, and database processing run on
the Azure Local appliance. Azure Arc provides cluster access, and an approved
Azure Container Registry supplies images. This is **not an air-gapped deployment**:
provisioning, downloads, and the demonstrated access path need external connectivity.

## How it works

1. **Simulate:** three fictional pumps cycle through healthy operation, fault
   ramp-up, sustained faults, recovery, and healthy operation again.
2. **Store:** the simulator inserts current UTC samples into TimescaleDB.
3. **Detect:** the application evaluates deterministic conditions approximately
   every five seconds and persists alerts and lifecycle events.
4. **Retrieve:** for an explanation request, it gathers bounded telemetry
   evidence and retrieves SOP sections using MiniLM embeddings and Qdrant.
5. **Explain:** the selected Qwen model returns an advisory explanation through
   authenticated, TLS-verified local inference.
6. **Review:** the dashboard displays evidence and sources and saves the diagnosis.

## Deployment boundaries and technology

| Boundary | Components and responsibilities |
|---|---|
| External access and images | Browser through an Arc-connected port-forward; approved Azure Container Registry |
| Solution-owned `telemetry-demo` namespace | Pump simulator, FastAPI telemetry application and static UI, TimescaleDB StatefulSet, 20 GiB CSI PVC, Secrets and ConfigMaps |
| Existing `assistant-demo` shared services | MiniLM embedding API and Qdrant; the existing warranty assistant remains a separate application |
| Existing `foundry-local-operator` model services | Qwen2.5 0.5B and 14B for operator-selected local inference |

**Technology:** Azure Local, Azure Arc-enabled Kubernetes, Foundry Local,
Python, FastAPI, PostgreSQL, TimescaleDB, Qdrant, MiniLM, Qwen, and PowerShell.

The [deployment architecture diagram](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/ARCHITECTURE.md#2-deployment-architecture)
shows the nested namespace boundaries, storage, shared services, and labeled
application connections.

## Run and extend the sample

This repository deploys the database, simulator, and telemetry application.
It does **not** provision a complete cluster or all shared AI infrastructure.
Before deployment, provide an Azure Local Arc-enabled Kubernetes cluster,
compatible storage, model endpoints, embedding API, Qdrant, and registry access.

| Guide | What you will find |
|---|---|
| [Deployment](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/DEPLOYMENT.md) | Ordered PowerShell steps for access, builds, preflight checks, deployment, validation, and upgrades |
| [Prerequisites](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/DEPENDENCIES.md) | Shared-service contracts and companion-project setup |
| [Architecture](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/ARCHITECTURE.md) | Data flows, rules, RAG, persistence, capacity, and design trade-offs |
| [Development](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/DEVELOPMENT.md) | Code map, APIs, configuration, tests, and SOP/rule authoring |
| [Demo and operations](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent/blob/main/docs/ANALYSIS.md) | UI walkthrough, model observations, troubleshooting, and recorded validation |

## Frequently asked questions

### Does this require Azure IoT Operations, MQTT, or Azure IoT Hub?

No. The demonstration simulator writes directly to TimescaleDB. Azure IoT
Operations, MQTT, Azure IoT Hub, and Azure-hosted database services are not required.

### Is this predictive maintenance?

It demonstrates simulated equipment condition monitoring and advisory diagnostics.
It does not predict remaining useful life, validate a physical model, or establish
production predictive-maintenance accuracy.

### Does the AI control the pumps or clear alerts?

No. The application controls the diagnostic workflow. The model cannot execute
SQL, acknowledge or clear alerts, operate equipment, or approve maintenance.

### Which local model should I use?

The recorded demonstration recommends **Qwen2.5 14B**. The 0.5B model invented
relationships between measurements in an observed explanation. Consult the
operations guide for the measured requests and limitations; these are not benchmarks.

### Is this production-ready?

No. It uses fictional data and single-replica services. It has no end-user
authentication, database TLS, backups/high availability, external alert delivery,
or equipment control. Review the documented boundaries before adapting it.

## Related Azure Local sample

The [azure-local-rag-assistant companion repository](https://github.com/MSFT-Innovation-Hub-India/azure-local-rag-assistant)
provides the warranty PDF assistant and the shared Qdrant, embedding and model
services this project reuses (see the
[README](https://github.com/MSFT-Innovation-Hub-India/azure-local-telemetry-ai-agent#companion-project-the-warranty-pdf-assistant)).
Follow this project's prerequisite guide for the specific shared-service contracts.

Published by [Microsoft Innovation Hub India](https://github.com/MSFT-Innovation-Hub-India).
