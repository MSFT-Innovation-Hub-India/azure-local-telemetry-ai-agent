# Shared-service prerequisites and fresh-lab preparation

Return to the [deployment sequence](DEPLOYMENT.md) after completing this page.
Commands use the variables and `Assert-NativeSuccess` helper defined there.
Nothing on this page is executed automatically by the telemetry deployers.

## 1. What must already exist

The ingestion-only demonstration needs an accessible Azure Local Kubernetes
cluster, an eligible worker, Azure Local CSI storage, CoreDNS and an approved ACR.
The full diagnosis demonstration additionally needs the services below.

These are real dependencies, not resources silently created by the telemetry app.
The exact names are deliberately enforced by the current implementation.

| Dependency | Required contract |
|---|---|
| Worker pool | Label `kubernetes.azure.com/agentpool=slmnodepool`; Ready, schedulable, no blocking taints/pressure |
| StorageClass | Normally `default`; provisioner `azlocal.csi.azure.com`; 20 GiB available for this solution |
| DNS | `kube-system/kube-dns-upstream` ClusterIP Service selecting actual CoreDNS pods |
| Cluster DNS suffix | `cluster.local` |
| Qdrant | `http://qdrant.assistant-demo.svc.cluster.local:6333`; API-key auth; REST collection/query APIs |
| Embeddings | `http://embeddings.assistant-demo.svc.cluster.local:8001/embed`; POST `{"texts":[...]}` |
| Model catalog | `assistant-demo/assistant-models`, ConfigMap key `models.json` |
| Shared credentials | `assistant-demo/assistant-credentials`, Secret keys listed below |
| Model CA | `foundry-local-operator/foundry-local-operator-ca-bundle`, ConfigMap key `ca.crt` |
| Small model | Service `qwen2-5-0-5b-cpu` in `foundry-local-operator`, HTTPS port 5000 |
| Large model | Service `qwen2-5-14b-cpu` in the same namespace, HTTPS port 5000 |

CoreDNS pods must have `k8s-app=kube-dns`. Qdrant and embedding pods must have
`app=qdrant` and `app=embeddings`. Model pods must have
`app.kubernetes.io/name` equal to their deployment ID. The current model Services
forward to pod TCP port **8443**, which the telemetry egress policy permits.
Different pod labels, target ports or cluster domains require reviewed changes;
Service DNS reachability alone is not enough.

### Embedding response

The API must return an object with:

- `model`: `sentence-transformers/all-MiniLM-L6-v2`;
- `revision`: `d13954661f83248295ba75c1ed411eef3b7b936e`;
- `vectors`: one nonzero, finite, 384-number vector per input text.

An API with a similar URL or a different MiniLM revision is not interchangeable.
The application rejects mismatched model/revision/count/dimensions rather than
searching an incompatible index.

### Model catalog and credentials

The `models.json` structure is:

```json
{
  "models": [
    {
      "id": "qwen2-5-0-5b-cpu",
      "label": "qwen2.5-0.5b",
      "model_id": "qwen2.5-0.5b-instruct-generic-cpu",
      "url": "https://qwen2-5-0-5b-cpu.foundry-local-operator.svc.cluster.local:5000/v1/chat/completions"
    },
    {
      "id": "qwen2-5-14b-cpu",
      "label": "qwen2.5-14b",
      "model_id": "qwen2.5-14b-instruct-generic-cpu",
      "url": "https://qwen2-5-14b-cpu.foundry-local-operator.svc.cluster.local:5000/v1/chat/completions"
    }
  ]
}
```

Use the model IDs actually resolved by the installed Foundry model deployments,
not an unverified spelling copied from a catalog example. The companion deployer
resolves them. The telemetry deployer currently requires **exactly these two
deployment IDs**; a catalog with an additional third model also fails validation.

The source Secret must contain:

```text
qdrant-key
model-key-qwen2-5-0-5b-cpu
model-key-qwen2-5-14b-cpu
```

Do not paste key values into documentation or command arguments. The deployer
copies selected values in memory to its own Secret. The CA must validate each
Service DNS certificate. Models must support authenticated OpenAI-compatible
chat completions with `stream=true`, SSE deltas, finish reason and `[DONE]`.
Usage counts are optional.

## 2. Inspect an existing matching environment

These commands do not change workloads or print Secret values:

```powershell
kubectl --context $Context -n kube-system get service kube-dns-upstream
Assert-NativeSuccess "Reading the upstream DNS Service"
kubectl --context $Context get storageclass $StorageClass
Assert-NativeSuccess "Reading the StorageClass"
kubectl --context $Context -n assistant-demo get service qdrant embeddings
Assert-NativeSuccess "Reading shared data Services"
kubectl --context $Context -n assistant-demo get pods -L app -o wide
Assert-NativeSuccess "Inspecting shared pod labels and readiness"
kubectl --context $Context -n assistant-demo get configmap assistant-models
Assert-NativeSuccess "Reading the model catalog metadata"
kubectl --context $Context -n assistant-demo get secret assistant-credentials
Assert-NativeSuccess "Reading credential metadata, not values"
kubectl --context $Context -n foundry-local-operator get configmap foundry-local-operator-ca-bundle
Assert-NativeSuccess "Reading CA metadata"
kubectl --context $Context -n foundry-local-operator get service qwen2-5-0-5b-cpu qwen2-5-14b-cpu -o wide
Assert-NativeSuccess "Reading model Services"
kubectl --context $Context -n foundry-local-operator get pods -L app.kubernetes.io/name -o wide
Assert-NativeSuccess "Inspecting model pod labels and readiness"
```

The catalog is non-secret and can be inspected without dumping credentials:

```powershell
$catalogJson = kubectl --context $Context -n assistant-demo get configmap assistant-models -o json
Assert-NativeSuccess "Reading the model catalog"
$catalog = ($catalogJson | ConvertFrom-Json).data.'models.json' | ConvertFrom-Json
$catalog.models | Select-Object id, label, model_id, url | Format-Table -AutoSize
```

Do not redeploy functioning shared workloads to satisfy a naming preference.
If the contracts already match, skip the fresh-lab sections below.

## 3. Optional: create only the missing CoreDNS alias Service

`kube-dns-upstream` is a lab-specific direct-CoreDNS Service, not a universal
Kubernetes default. It bypasses the NodeLocal DNS path that caused problems in
the original lab. The telemetry code currently requires this name.

First ask the platform administrator to confirm the cluster's DNS layout and
approve a **new Service only** in `kube-system`. Do not change CoreDNS, NodeLocal
DNS, Cilium or the existing `kube-dns` Service. Do not use this recipe if the source
Service selects a host-network DNS cache instead of actual CoreDNS pods.

Inspect the existing Service, selectors and endpoint destinations:

```powershell
kubectl --context $Context -n kube-system get service kube-dns -o wide
kubectl --context $Context -n kube-system get pods -l k8s-app=kube-dns -o wide
kubectl --context $Context -n kube-system get endpointslices -l kubernetes.io/service-name=kube-dns -o wide
```

Only if the alias is absent and the preceding check is approved:

```powershell
$existingAlias = kubectl --context $Context -n kube-system get service kube-dns-upstream --ignore-not-found -o name
Assert-NativeSuccess "Checking for an existing DNS alias"
if ($existingAlias) { throw "DNS alias already exists; inspect and reuse it, do not overwrite it." }

$dnsJson = kubectl --context $Context -n kube-system get service kube-dns -o json
Assert-NativeSuccess "Reading the existing DNS Service"
$dns = $dnsJson | ConvertFrom-Json
if ($dns.spec.selector.'k8s-app' -ne "kube-dns") {
    throw "DNS selectors differ from the documented policy contract; ask the platform administrator."
}
$ports = @($dns.spec.ports | Where-Object { $_.port -eq 53 } | ForEach-Object {
    @{ name = $_.name; port = $_.port; targetPort = $_.targetPort; protocol = $_.protocol }
})
if ($ports.Count -ne 2) { throw "Expected TCP and UDP DNS ports; review the Service manually." }
$alias = @{
    apiVersion = "v1"
    kind = "Service"
    metadata = @{ name = "kube-dns-upstream"; namespace = "kube-system" }
    spec = @{ selector = $dns.spec.selector; ports = $ports }
}
$alias | ConvertTo-Json -Depth 8 |
    kubectl --context $Context create -f -
Assert-NativeSuccess "Creating the additional DNS Service only"
kubectl --context $Context -n kube-system get endpointslices -l kubernetes.io/service-name=kube-dns-upstream -o wide
```

This is an optional, administrator-owned prerequisite write, **not** an expansion
of the telemetry deployer's write boundary. If the Service has no ready CoreDNS
endpoints, stop and resolve the prerequisite before deploying the demo.

## 4. Fresh lab: install the model infrastructure first

Provisioning Azure Local, Arc registration, CSI and the Foundry Local operator
is a platform prerequisite, not implemented in this repository. Follow the
environment's supported installation process; the original demonstration used
the [Azure Local Foundry Local lab](https://docs.almr.adaptivecloudlab.com/eng-22325/foundry-local/run-inference.html?tabs=powershell)
and its preceding setup pages.

The lab reference is
[Azure-Local-Samples-101](https://github.com/MSFT-Innovation-Hub-India/Azure-Local-Samples-101).
Do not assume it contains this custom telemetry solution or every enhancement in
the local companion project.

For the bootstrap below you need an approved copy of the **companion source**
used in the original environment (`qwen2.5-sample`), including its model manifests,
ACR builder and `tools.deploy_assistant`. It is not vendored here. Transfer its
source separately, without `.local`, credentials or virtual environments.

After the operator is installed, check its CRD and existing models:

```powershell
kubectl --context $Context get crd modeldeployments.foundrylocal.azure.com
Assert-NativeSuccess "Checking the Foundry Local operator CRD"
kubectl --context $Context -n foundry-local-operator get modeldeployments
kubectl --context $Context get nodes -o wide
kubectl --context $Context describe nodes
```

Review model availability, licenses, node capacity and download connectivity.
The companion's 0.5B manifest requests 2 CPU / 6 GiB and limits 4 CPU / 10 GiB.
Its 14B manifest requests 8 CPU / 16 GiB and limits 16 CPU / 32 GiB, targeting
`slmnodepool`. These requirements are **in addition to** telemetry and shared
services. Do not resize or move existing workloads to make room.

Only on an approved fresh setup, and only for a model not already deployed:

```powershell
kubectl --context $Context create -f "$CompanionRoot\deploy\qwen2.5-0.5b.yaml"
Assert-NativeSuccess "Creating the missing 0.5B model"
kubectl --context $Context create -f "$CompanionRoot\deploy\qwen2.5-14b.yaml"
Assert-NativeSuccess "Creating the missing 14B model"
```

`create`, rather than `apply`, intentionally refuses an existing resource.
Skip either command if that model already exists. The manifests reference model
asset version 4; availability/operator compatibility must be checked in the
target environment. Allow model downloads/startup to finish and inspect:

```powershell
kubectl --context $Context -n foundry-local-operator get modeldeployments
kubectl --context $Context -n foundry-local-operator get pods -o wide
kubectl --context $Context -n foundry-local-operator get service qwen2-5-0-5b-cpu qwen2-5-14b-cpu
```

Continue only when both model pods are Ready, their Services/keys exist and the
trusted CA is present. The observed 14B artifact download took roughly nine
minutes in the original lab; startup can take longer elsewhere.

## 5. Fresh lab: build/deploy the companion shared stack

This optional path creates the companion's embedding API, Qdrant, warranty app
and document helper, including its own storage. It is not a minimal telemetry-only
AI infrastructure installer. No warranty PDF indexing is needed for telemetry.
Alternatively, a platform team can provide the exact contracts in Section 1.

**Run this only if `assistant-demo` is absent.** If the namespace is already
deployed, use its own runbook and placement-preserving upgrade process rather than
this fresh-install recipe.

Use the variables, Python environment and isolated ACR profile from the deployment
guide. All companion paths below are local Windows paths.

```powershell
$existingAssistant = kubectl --context $Context get namespace assistant-demo --ignore-not-found -o name
Assert-NativeSuccess "Checking for an existing companion stack"
if ($existingAssistant) { throw "Companion stack exists. Reuse it or follow its guarded upgrade runbook." }

Push-Location $CompanionRoot
try {
    .\tools\build_acr.ps1 -Registry $Registry -Subscription $AcrSubscription `
        -AzureConfigDir $AcrConfigDir -RepositoryPrefix "ssrikantan/azure-local-pdf"
    Assert-NativeSuccess "Building the companion images"
    $sharedImages = Get-Content -Raw .\.local\acr-images.json | ConvertFrom-Json
    $sharedArgs = @(
        "--context", $Context, "--storage-class", $StorageClass,
        "--dns-service", "kube-dns-upstream",
        "--app-image", $sharedImages.app_image,
        "--embeddings-image", $sharedImages.embeddings_image,
        "--qdrant-image", $sharedImages.qdrant_image,
        "--model-deployment", "qwen2-5-0-5b-cpu",
        "--model-deployment", "qwen2-5-14b-cpu"
    )
    & $Python -B -m tools.deploy_assistant @sharedArgs
    Assert-NativeSuccess "Read-only companion preflight"

    $previousConfig = $env:AZURE_CONFIG_DIR
    try {
        $env:AZURE_CONFIG_DIR = $AcrConfigDir
        $loginJson = az acr login --name $Registry --subscription $AcrSubscription `
            --expose-token --only-show-errors -o json
        Assert-NativeSuccess "Obtaining temporary registry pull credentials"
        $login = $loginJson | ConvertFrom-Json
        if (-not $login.accessToken -or -not $login.loginServer) {
            throw "Registry did not return valid credentials."
        }
    }
    finally { $env:AZURE_CONFIG_DIR = $previousConfig }
    $auth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        "00000000-0000-0000-0000-000000000000:$($login.accessToken)"
    ))
    $dockerJson = @{ auths = @{ $login.loginServer = @{ auth = $auth } } } |
        ConvertTo-Json -Depth 5 -Compress
    $dockerJson | & $Python -B -m tools.deploy_assistant @sharedArgs --registry-config-stdin --apply
    Assert-NativeSuccess "Deploying the fresh companion stack"
}
finally {
    $loginJson = $login = $auth = $dockerJson = $null
    Pop-Location
}
```

The token remains in process memory until cleanup/collection and is sent only to
the deployer; do not print it or run this under shell tracing/transcription that
captures secrets. This lab credential is short-lived, not a dedicated pull-only
identity.

```powershell
kubectl --context $Context -n assistant-demo rollout status statefulset/qdrant --timeout=600s
Assert-NativeSuccess "Waiting for Qdrant"
kubectl --context $Context -n assistant-demo rollout status deployment/embeddings --timeout=900s
Assert-NativeSuccess "Waiting for embeddings"
kubectl --context $Context -n assistant-demo rollout status deployment/assistant-web --timeout=600s
Assert-NativeSuccess "Waiting for the separate warranty UI"
kubectl --context $Context -n assistant-demo rollout status deployment/documents --timeout=600s
Assert-NativeSuccess "Waiting for the companion document helper"
kubectl --context $Context -n assistant-demo get pvc,pods
```

Recheck Section 2, then return to the telemetry deployment guide.
Do not rerun this bootstrap as part of routine telemetry upgrades.
