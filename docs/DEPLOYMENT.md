# Reproduce the telemetry demonstration on Azure Local

This is the ordered deployment runbook for an **existing Azure Local,
Arc-enabled Kubernetes cluster**. It does not provision the appliance, register
Arc, install CSI/Foundry extensions or create a node pool/registry.

All commands are PowerShell 5.1/7-compatible and use Windows local paths.
Do not paste commands containing unedited placeholders. Run from this solution's
root, not from the companion project, except where explicitly directed.

## 0. Prerequisites and deployment stages

### Required access and tools

- Python **3.12** on PATH, Azure CLI and `kubectl`; no local Docker or Node.js.
- Authorized access to the target Arc-connected cluster and its API/proxy.
- An approved ACR with ACR Tasks build, image import, metadata and pull access.
  Registry resource-provider/RBAC/network prerequisites must already be approved.
- Linux AMD64 workers, working CNI/NetworkPolicy enforcement and
  `azlocal.csi.azure.com` block storage with at least 20 GiB available.
- A Ready, untainted worker in `slmnodepool` with sufficient unreserved capacity.
  Neither deployer creates capacity or evicts/moves other workloads.
- For the AI phase, all [shared-service contracts](DEPENDENCIES.md).
- Build-time access to the Python base image/package feed and upstream Timescale
  image; worker access to ACR. Model provisioning can need additional downloads.
- Cluster RBAC to list nodes/pods/StorageClasses; inspect named shared
  ConfigMaps/Secrets; manage owned telemetry resources; exec SQL in its DB pod;
  and create the specifically documented additive shared NetworkPolicy.

The validated cluster was AKS Arc Kubernetes v1.33.10 on Azure Linux 3.
Other supported versions/platform configurations require their own verification.
These scripts are not a general installer for arbitrary Arc-connected clusters.

| Stage | Writes | Checkpoint |
|---|---|---|
| Local preparation | Local venv and private CLI profile | Tests/help load |
| Shared prerequisites, if missing | Separately approved platform/companion setup | Exact dependency contracts |
| Image publication | Approved ACR repositories | Immutable image metadata |
| Foundation | `telemetry-demo` only | DB/PVC/ingestion/SQL tests |
| Analysis | Owned app/schema plus one shared NetworkPolicy | Detector, SOP index, UI, inference |
| Browser access | Local proxy/port-forward processes | Independent URLs |

You can stop after the foundation stage for an ingestion-only demonstration.

### Obtain the source

Copy/checkout **this telemetry solution's source**, not just the public lab
reference. Transfer `telemetry`, `static`, `sops`, `db`, `deploy`, `tools`, `tests`,
`docs`, the Dockerfile, requirements, README and ignore files.
Do not copy `.venv`, `.local`, kubeconfig, Azure profiles or live credentials
between environments. There is no assumed public clone URL for this custom code.

For a fresh AI stack, also obtain the separately approved companion source
described in the [dependency guide](DEPENDENCIES.md#4-fresh-lab-install-the-model-infrastructure-first).

## 1. Set target variables and prepare the local shell

Use one main PowerShell terminal for Sections 1-7 and 9-10. Set **your** values:

```powershell
$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\demos\realtime-telemetry-analysis"
$CompanionRoot = "C:\demos\qwen2.5-sample"
$Context = "<target-kubectl-context>"
$Registry = "<approved-acr-name>"
$AcrTenant = "<registry-tenant-id>"
$AcrSubscription = "<registry-subscription-id>"
$AcrConfigDir = Join-Path $ProjectRoot ".local\acr-azure"
$StorageClass = "default"
$NodePool = "slmnodepool"

if (@($Context, $Registry, $AcrTenant, $AcrSubscription) |
    Where-Object { $_ -match "^<" }) {
    throw "Replace the target environment placeholders before continuing."
}
Set-Location $ProjectRoot
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed; stop and inspect before continuing." }
}
Get-Command python, kubectl, az -ErrorAction Stop
python --version
Assert-NativeSuccess "Checking Python"
```

`$Registry` is the resource name, not `https://...` or the login-server hostname.
Keep `$NodePool` at `slmnodepool` for the unmodified full solution: analysis
currently has no `--nodepool` argument.

Create the environment on a fresh machine; use an existing matching venv if
already prepared:

```powershell
python -m venv .venv
Assert-NativeSuccess "Creating the Python environment"
$Python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $Python -m pip install -r .\requirements.txt
Assert-NativeSuccess "Installing application/test dependencies"
& $Python -m pip check
Assert-NativeSuccess "Checking installed dependencies"
& $Python -B -m unittest discover -s tests -v
Assert-NativeSuccess "Running unit tests"
& $Python -B -m tools.deploy --help
Assert-NativeSuccess "Loading the foundation CLI"
& $Python -B -m tools.deploy_analysis --help
Assert-NativeSuccess "Loading the analysis CLI"
```

Expected: 22 passing tests for the shipped release. A Starlette TestClient
httpx deprecation warning was observed; it is not a test failure.

## 2. Establish cluster access without changing another subscription

If a working Arc proxy is already running, reuse it. Otherwise open a
**separate terminal A**, set the target values there, and leave the proxy running:

```powershell
$env:AZURE_CONFIG_DIR = "C:\demos\profiles\cluster-azure"
$ClusterTenant = "<cluster-tenant-id>"
$ClusterSubscription = "<cluster-subscription-id>"
$ArcResourceGroup = "<arc-cluster-resource-group>"
$ArcClusterName = "<arc-connected-cluster-name>"
New-Item -ItemType Directory -Force $env:AZURE_CONFIG_DIR | Out-Null
az login --tenant $ClusterTenant --output none
if ($LASTEXITCODE -ne 0) { throw "Cluster-profile sign-in failed." }
az connectedk8s proxy --subscription $ClusterSubscription `
    --resource-group $ArcResourceGroup --name $ArcClusterName
```

A platform may instead provide a direct kubeconfig; use its approved access
method. The proxy can update kubeconfig/current context, but every deployment
command below still specifies `$Context`. Terminal variables do not carry across
terminals. Set `$Context` in the main shell to the actual generated context.

In the **main terminal**, verify the intended cluster:

```powershell
kubectl config get-contexts
Assert-NativeSuccess "Listing Kubernetes contexts"
kubectl --context $Context cluster-info
Assert-NativeSuccess "Reaching the intended cluster"
kubectl --context $Context get nodes -o wide
Assert-NativeSuccess "Reading nodes"
kubectl --context $Context get pods -A -o wide
Assert-NativeSuccess "Reading existing workloads"
kubectl --context $Context describe nodes
Assert-NativeSuccess "Inspecting allocations and node conditions"
kubectl --context $Context get storageclass $StorageClass -o yaml
Assert-NativeSuccess "Inspecting storage"
kubectl --context $Context get nodes -l "kubernetes.azure.com/agentpool=$NodePool"
Assert-NativeSuccess "Finding the intended pool"
```

Confirm the StorageClass provisioner is `azlocal.csi.azure.com`; review its reclaim
policy and binding mode. The original `default` class used `Delete` and did not
permit expansion. Missing Metrics API is not a reason to install/change extensions;
the guard uses reservations, not `kubectl top`.

Useful RBAC checks (a `no` answer is a prerequisite blocker):

```powershell
kubectl --context $Context auth can-i list pods --all-namespaces
kubectl --context $Context auth can-i get nodes
kubectl --context $Context auth can-i create namespaces
kubectl --context $Context auth can-i get secret/assistant-credentials -n assistant-demo
kubectl --context $Context auth can-i create networkpolicies.networking.k8s.io -n assistant-demo
```

These are examples, not a complete RBAC policy or a request for blanket admin.
Namespace ownership conflicts, unreadable dependencies or insufficient node
capacity must be resolved with the platform owner, not by removing safeguards.

## 3. Sign in to ACR using a dedicated profile

The ACR may be in a different subscription/tenant from the cluster.
The telemetry builder/deployer do **not** accept a subscription argument; they
use the selected subscription in this private profile. Select it only there:

```powershell
New-Item -ItemType Directory -Force $AcrConfigDir | Out-Null
$AcrConfigDir = (Resolve-Path $AcrConfigDir).Path
$previousConfig = $env:AZURE_CONFIG_DIR
try {
    $env:AZURE_CONFIG_DIR = $AcrConfigDir
    az login --tenant $AcrTenant --output none
    Assert-NativeSuccess "Registry-profile sign-in"
    az account set --subscription $AcrSubscription
    Assert-NativeSuccess "Selecting the subscription in the isolated registry profile"
    az account show --query "{subscription:id,tenant:tenantId}" -o json
    Assert-NativeSuccess "Verifying the registry profile"
    az acr show --name $Registry --query "{name:name,server:loginServer}" -o json
    Assert-NativeSuccess "Verifying approved registry access"
}
finally { $env:AZURE_CONFIG_DIR = $previousConfig }
```

Do not enable the registry admin user, create a registry, change registry roles,
or run `--attach-acr` as an assumed Azure Local fix. Use the organization's
approved existing registry/pull identity process.

Now complete [shared-service preparation](DEPENDENCIES.md) if needed. That page
uses the variables/helper above. On the existing demonstration cluster, simply
inspect and reuse the services; do not run the fresh-lab bootstrap.

## 4. Build and pin all three telemetry images

These commands publish code/SOPs/static assets to the **approved ACR**.
No documents or credentials outside the build allowlist should enter the context.

```powershell
Set-Location $ProjectRoot
.\tools\build_acr.ps1 -Registry $Registry -AzureConfigDir $AcrConfigDir
Assert-NativeSuccess "Building the simulator and mirroring TimescaleDB"

.\tools\build_acr.ps1 -Registry $Registry -AzureConfigDir $AcrConfigDir -AppOnly
Assert-NativeSuccess "Building the telemetry application"

$images = Get-Content -Raw .\.local\images.json | ConvertFrom-Json
$images | Select-Object registry, server, database_image, simulator_image, app_image | Format-List
```

The first build creates the simulator and mirrors the pinned upstream
`timescale/timescaledb` PostgreSQL 17 image:

```text
sha256:6a6b7d7a346d7c6be03a310c240706f3bbc6d7adbdf3fbc07823570b34337f5e
```

The second adds `app_image`, retaining the first two digests. Both simulator and
app use the same Dockerfile; their runtime command differs in Kubernetes.
Expected metadata has all three references under:

```text
<registry-server>/ssrikantan/realtime-telemetry/timescaledb@sha256:...
<registry-server>/ssrikantan/realtime-telemetry/simulator@sha256:...
<registry-server>/ssrikantan/realtime-telemetry/app@sha256:...
```

The repository prefix is currently fixed in builder/validators, not a flag.
The build is Linux AMD64. No local Docker daemon is used. `.local\images.json`
contains metadata, not passwords; `.local\acr-azure` contains sensitive sign-in
state and must never be published.

## 5. Define preservation checks before deployment

The deployers save their own baseline files, but the following operator checks
also record node placement before **each** phase. Load these two functions into
the main terminal once:

```powershell
function Save-PodBaseline([string]$Path) {
    $raw = kubectl --context $Context get pods -A -o json
    Assert-NativeSuccess "Capturing existing pod identities"
    $snapshot = @(
        ($raw | ConvertFrom-Json).items |
        Where-Object {
            $_.status.phase -notin @("Succeeded", "Failed") -and
            -not ($_.metadata.namespace -eq "telemetry-demo" -and
                  $_.metadata.labels.app -eq "telemetry-web")
        } |
        ForEach-Object {
            $restarts = @{}
            foreach ($state in (@($_.status.containerStatuses) + @($_.status.initContainerStatuses))) {
                if ($null -ne $state) { $restarts[$state.name] = $state.restartCount }
            }
            [pscustomobject]@{
                namespace = $_.metadata.namespace
                name = $_.metadata.name
                uid = $_.metadata.uid
                node = $_.spec.nodeName
                ready = @($_.status.conditions | Where-Object {
                    $_.type -eq "Ready" -and $_.status -eq "True"
                }).Count -gt 0
                restarts = $restarts
            }
        }
    )
    ConvertTo-Json -InputObject $snapshot -Depth 8 |
        Set-Content -Encoding utf8 -Path $Path
}

function Test-PodBaseline([string]$Path) {
    $before = Get-Content -Raw $Path | ConvertFrom-Json
    $raw = kubectl --context $Context get pods -A -o json
    Assert-NativeSuccess "Reading pods for preservation verification"
    $lookup = @{}
    foreach ($pod in ($raw | ConvertFrom-Json).items) {
        $lookup["$($pod.metadata.namespace)/$($pod.metadata.name)"] = $pod
    }
    foreach ($old in $before) {
        $key = "$($old.namespace)/$($old.name)"
        $pod = $lookup[$key]
        if (-not $pod -or $pod.metadata.uid -ne $old.uid -or $pod.spec.nodeName -ne $old.node) {
            throw "Existing pod identity/placement changed: $key"
        }
        $restarts = @{}
        foreach ($state in (@($pod.status.containerStatuses) + @($pod.status.initContainerStatuses))) {
            if ($null -ne $state) { $restarts[$state.name] = $state.restartCount }
        }
        foreach ($entry in $old.restarts.PSObject.Properties) {
            if (-not $restarts.ContainsKey($entry.Name) -or $restarts[$entry.Name] -ne $entry.Value) {
                throw "Existing container restart count changed: $key / $($entry.Name)"
            }
        }
        $ready = @($pod.status.conditions | Where-Object {
            $_.type -eq "Ready" -and $_.status -eq "True"
        }).Count -gt 0
        if ($old.ready -and -not $ready) { throw "Previously Ready pod is not Ready: $key" }
    }
    Write-Output "PASS: $(@($before).Count) baseline pods retain identity, placement and restart counts."
}
```

The telemetry web pod is excluded because app deployment intentionally replaces
it. The foundation DB/simulator **are included** in the later analysis baseline.
Unexpected unrelated cluster churn can also fail these strict checks: investigate
the named change rather than automatically attributing it to this deployment or
restarting more workloads.

## 6. Deploy and verify the database/simulator foundation

### 6.1 Read-only preflight

```powershell
Save-PodBaseline -Path .\.local\demo-foundation-before.json
& $Python -B -m tools.deploy --context $Context --nodepool $NodePool `
    --storage-class $StorageClass --preserve-placement
Assert-NativeSuccess "Foundation preflight"
```

`--preserve-placement` is safe on an initial telemetry deployment and mandatory
on subsequent ones. A successful preflight prints unreserved capacity and
`Preflight passed. Read-only mode: no resources changed.`
It is not a runtime load test.

### 6.2 Explicit apply

```powershell
& $Python -B -m tools.deploy --context $Context --nodepool $NodePool `
    --storage-class $StorageClass --preserve-placement `
    --azure-config-dir $AcrConfigDir --apply
Assert-NativeSuccess "Applying the foundation"

kubectl --context $Context -n telemetry-demo rollout status statefulset/timescaledb --timeout=300s
Assert-NativeSuccess "Waiting for TimescaleDB initialization"
kubectl --context $Context -n telemetry-demo rollout status deployment/pump-simulator --timeout=180s
Assert-NativeSuccess "Waiting for the simulator"
kubectl --context $Context -n telemetry-demo get pods,pvc -o wide
Assert-NativeSuccess "Inspecting foundation resources"
Test-PodBaseline -Path .\.local\demo-foundation-before.json
```

Expected: `timescaledb-0` and one simulator pod Ready; `timescaledb-data` Bound,
20 GiB; eligible pinned worker placement. The first database startup initializes
the schema and random admin/writer/reader credentials. These are stored in the
owned `telemetry-database` Secret, not local files.

### 6.3 Prove that data is live and permissions are correct

```powershell
kubectl --context $Context -n telemetry-demo logs deployment/pump-simulator --tail=10
Assert-NativeSuccess "Reading simulator commit logs"
Get-Content -Raw .\db\inspect.sql |
    kubectl --context $Context -n telemetry-demo exec -i timescaledb-0 -- `
    psql -U postgres -d telemetry -f -
Assert-NativeSuccess "Inspecting the extension, hypertable and measurements"

Start-Sleep -Seconds 10
Get-Content -Raw .\db\inspect.sql |
    kubectl --context $Context -n telemetry-demo exec -i timescaledb-0 -- `
    psql -U postgres -d telemetry -f -
Assert-NativeSuccess "Confirming advancing timestamps and counts"

Get-Content -Raw .\tests\integration.sql |
    kubectl --context $Context -n telemetry-demo exec -i timescaledb-0 -- `
    psql -U postgres -d telemetry -f -
Assert-NativeSuccess "Checking live freshness, permissions and deduplication"
```

Expected: TimescaleDB extension, `telemetry.samples` in the hypertable listing,
three assets with increasing counts/current timestamps, age normally below 15 s,
and integration checks completing with `ROLLBACK`, not an exception.
The integration test writes probe rows inside a rolled-back transaction and
briefly locks this demo's sample table for duplicate-count validation.

Do not use a count from the original lab as the expected count in a new lab.
For ingestion-only use, stop here; no Qdrant/embedding/model access is needed.

## 7. Deploy the independent analysis application

Confirm all [dependency checks](DEPENDENCIES.md#2-inspect-an-existing-matching-environment)
before this stage. The namespace and live DB must already exist, and
`.local\images.json` must include the app digest.

```powershell
Save-PodBaseline -Path .\.local\demo-analysis-before.json
& $Python -B -m tools.deploy_analysis --context $Context --preserve-placement
Assert-NativeSuccess "Analysis preflight"

& $Python -B -m tools.deploy_analysis --context $Context --preserve-placement `
    --azure-config-dir $AcrConfigDir --apply
Assert-NativeSuccess "Applying the independent analysis app"

kubectl --context $Context -n telemetry-demo rollout status deployment/telemetry-web --timeout=600s
Assert-NativeSuccess "Waiting for the detector-ready application"
kubectl --context $Context -n telemetry-demo get pods,pvc -o wide
kubectl --context $Context -n telemetry-demo logs deployment/telemetry-web --tail=30
Test-PodBaseline -Path .\.local\demo-analysis-before.json
```

Preflight reads the source model catalog/CA/credentials and execs a read-only DB
role-existence check. Apply copies selected keys/CA into owned telemetry
resources, refreshes the owned pull Secret, adds the narrow shared policy, applies
the transactional analysis migration, then deploys **only** the web application.
Database, simulator and shared pod templates are not reapplied.

Expected: one Ready web pod, fresh detector ticks, then a log reporting 16 SOP
passages indexed. Index dependencies can retry separately; readiness alone does
not prove indexing or inference. Validate the API in the next section.

## 8. Open the independent applications

Leave terminal A's Arc proxy active. In a **separate telemetry tunnel terminal**,
set your context explicitly and keep the command running:

```powershell
$Context = "<target-kubectl-context>"
kubectl --context $Context -n telemetry-demo port-forward svc/telemetry-web `
    --address 127.0.0.1 8090:80
```

If the separate warranty application is installed, use **another terminal**:

```powershell
$Context = "<target-kubectl-context>"
kubectl --context $Context -n assistant-demo port-forward svc/assistant-web `
    --address 127.0.0.1 8080:80
```

Open http://127.0.0.1:8090 and http://127.0.0.1:8080 respectively. No model
port-forward or model selection changes in the warranty app are necessary.
If a local port is already in use, reuse the known tunnel or choose another
unused local port; do not kill processes by name.

Back in the main shell:

```powershell
$BaseUrl = "http://127.0.0.1:8090"
$health = Invoke-WebRequest -UseBasicParsing "$BaseUrl/healthz" -TimeoutSec 20
$ready = Invoke-WebRequest -UseBasicParsing "$BaseUrl/readyz" -TimeoutSec 20
if ($health.StatusCode -ne 200 -or $ready.StatusCode -ne 200) {
    throw "Application health/readiness failed."
}
$overview = Invoke-RestMethod "$BaseUrl/api/overview" -TimeoutSec 20
$overview.detector | Format-List
$overview.index | Format-List
$overview.models | Format-Table
if (-not $overview.index.ready) {
    throw "Index is not ready yet. Inspect its error and app logs; retry this check after correction."
}
if (@($overview.documents).Count -ne 3 -or $overview.index.details.chunk_count -ne 16) {
    throw "The shipped SOP package was not fully published."
}
if (@($overview.models).Count -ne 2) { throw "Both models must be available." }

$before = $overview
Start-Sleep -Seconds 10
$after = Invoke-RestMethod "$BaseUrl/api/overview" -TimeoutSec 20
if (@($after.equipment).Count -ne 3) { throw "Expected three simulated pumps." }
foreach ($asset in $after.equipment) {
    $age = ([datetimeoffset]$after.server_time - [datetimeoffset]$asset.measured_at).TotalSeconds
    $old = $before.equipment | Where-Object { $_.equipment_id -eq $asset.equipment_id }
    if ($age -gt 15 -or $age -lt -5 -or
        [datetimeoffset]$asset.measured_at -le [datetimeoffset]$old.measured_at) {
        throw "Telemetry is stale, future-dated or not advancing: $($asset.equipment_id)"
    }
}
Write-Output "PASS: three fresh advancing assets, three SOPs / 16 sections and two models."
```

An application replacement ends a Service port-forward attached to its old pod.
Reconnect **only the affected telemetry tunnel** after upgrading the app; do not
restart the Arc connection or warranty tunnel as a routine response.

### Optional: verify each actual model, not just its dropdown entry

This generates and saves a diagnosis and uses shared inference compute.
Allow the simulator's fault phase to create an alert first. A resolved alert can
also be inspected with its historical evidence. Run sequentially, not in parallel:

```powershell
$overview = Invoke-RestMethod "$BaseUrl/api/overview" -TimeoutSec 20
$alert = $overview.alerts | Where-Object { $_.rule_id -eq "bearing" } | Select-Object -First 1
if (-not $alert) { throw "No bearing alert yet; allow the fault ramp and sustained trigger window to finish." }
$Model = "qwen2-5-14b-cpu"
$body = @{ model = $Model } | ConvertTo-Json -Compress
$diagnosis = Invoke-RestMethod "$BaseUrl/api/alerts/$($alert.id)/diagnose" `
    -Method Post -ContentType "application/json" -Body $body -TimeoutSec 360
if ($diagnosis.model_id -ne $Model -or @($diagnosis.sources).Count -lt 1) {
    throw "Diagnosis did not retain the chosen model and sources."
}
$diagnosis | Select-Object id, model_id, elapsed_seconds, usage | Format-List
$diagnosis.result
```

Repeat with `$Model = "qwen2-5-0-5b-cpu"` and the same request block if you want
the small-model comparison. Usage is null in streaming mode (the default for 14B),
which does not return token counts; add `stream = $false` for 0.5B to see them. Missing usage is null, not zero. Inspect source
passages and factual consistency; HTTP 200 is not an accuracy test.
The original live requests took about 75 s / 15 s respectively; **14B is
recommended** because the small model invented measurement relationships.

Finish by repeating `Test-PodBaseline` for the analysis baseline. See the
[demo walkthrough](ANALYSIS.md#using-the-telemetry-ui) for acknowledgements,
related-parameter checks, recovery and saved comparisons. Alerts recur within
the ten-minute cycle; do not restart the simulator merely to force a fault.

## 9. Subsequent releases and credential maintenance

### Application-only upgrade

```powershell
Set-Location $ProjectRoot
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item .\.local\images.json ".\.local\images-before-$stamp.json"
Save-PodBaseline -Path .\.local\demo-analysis-before.json
& $Python -B -m unittest discover -s tests -v
Assert-NativeSuccess "Checking the release"
.\tools\build_acr.ps1 -Registry $Registry -AzureConfigDir $AcrConfigDir -AppOnly
Assert-NativeSuccess "Building only the app"
& $Python -B -m tools.deploy_analysis --context $Context --preserve-placement
Assert-NativeSuccess "Analysis upgrade preflight"
& $Python -B -m tools.deploy_analysis --context $Context --preserve-placement `
    --azure-config-dir $AcrConfigDir --apply
Assert-NativeSuccess "Applying only the app upgrade"
kubectl --context $Context -n telemetry-demo rollout status deployment/telemetry-web --timeout=600s
Assert-NativeSuccess "Waiting for the upgraded app"
Test-PodBaseline -Path .\.local\demo-analysis-before.json
```

Reconnect only its port-forward, repeat the API checks, and confirm old alert,
acknowledgement and diagnosis records are still visible.
Do not rerun the foundation or companion deployer for an app-only release.

For simulator-only releases, use `-SimulatorOnly` and the foundation deployer
with `--preserve-placement`; it retains the database image but deliberately
replaces the simulator, resetting its cycle. The foundation manifest is reapplied,
so review the whole intended foundation change first.

For a compatible code/UI rollback, restore approved previous image metadata and
use the same guarded app deployment. Do not blindly roll back across schema,
SOP/rule-version or credential changes. There are no automatic down-migrations.

### Refresh only the telemetry image-pull Secret

Lab Entra pull tokens normally expire in roughly three hours. Existing containers
continue running, but rescheduling/restarting may require a new pull.
Refresh before the demonstration or a planned rollout:

```powershell
& $Python -B -m tools.deploy --context $Context --nodepool $NodePool `
    --storage-class $StorageClass --preserve-placement `
    --azure-config-dir $AcrConfigDir --apply --refresh-pull-only
Assert-NativeSuccess "Refreshing only the telemetry pull Secret"
```

This still runs the foundation's read-only prerequisite/capacity checks, then
updates only `telemetry-image-pull`. It does not rotate DB credentials or restart
pods. It does not refresh the companion namespace's separate pull Secret.
An approved durable pull-only identity is a production prerequisite.

### Shared model/Qdrant key or CA rotation

Copied credentials are not automatically synchronized. First let the shared
service owner complete the rotation and update the source catalog/Secret/CA.
Run the guarded analysis apply with unchanged images to recopy them, then restart
**only** the owned app so startup-cached clients/catalog reload:

```powershell
& $Python -B -m tools.deploy_analysis --context $Context --preserve-placement `
    --azure-config-dir $AcrConfigDir --apply
Assert-NativeSuccess "Copying the approved rotated credentials/trust"
kubectl --context $Context -n telemetry-demo rollout restart deployment/telemetry-web
Assert-NativeSuccess "Restarting only the telemetry application"
kubectl --context $Context -n telemetry-demo rollout status deployment/telemetry-web --timeout=600s
Assert-NativeSuccess "Waiting for reloaded clients"
```

Preserve the original `telemetry-database` and `telemetry-agent-credentials`
Secrets. If data/roles exist without their original passwords, the deployer
refuses silent regeneration. Restore through an approved recovery process.

## 10. Adapting a different environment: supported vs source changes

| Difference | Supported as-is? | Required action |
|---|---|---|
| Different cluster/context, RG, tenant/subscription | Yes | Change access/session variables; explicit context and isolated ACR profile |
| Different approved ACR name | Yes | Fresh builds produce matching server/digests; do not reuse another registry's metadata |
| Different Azure Local CSI StorageClass name | Yes | Foundation `--storage-class`; same provisioner required |
| Different worker hostname | Yes | Initial guard selects/pins an eligible target-pool worker |
| Different local UI port | Yes | Change local port-forward and `$BaseUrl` |
| Different node-pool name | Foundation only | Analysis hardcodes `slmnodepool`; review/update its selection checks too |
| Different namespace, DB name, quota or PVC size | No flag | Coordinate manifests, deployer guards, SQL, DNS, roles and policies |
| Different DNS Service name/domain/labels | No flag for telemetry | Coordinate both deployers/manifests/policies; see dependency contract |
| Different embedding service/model/revision | Partly configurable URL only | Validate transport/response/model/dimensions; review index/versioning and policies |
| Different model IDs/namespace/Service URLs | No general plug-in flag | Update source catalog checks, model loader, keys, trust and network policy together |
| Different model target pod port/labels | No automatic discovery | Update narrow egress selectors/port after review |
| Only one model or an extra third model | No | Current analysis deployer requires exactly the two documented IDs |
| Arbitrary non-Azure-Local Arc cluster or ARM nodes | Not validated | CSI/platform/image/model compatibility work required |

Do not work around a failed guard by relabeling workers, adding control-plane
tolerations, removing ownership checks, moving existing pods or raising quotas
silently. Either reproduce the documented contracts or make and test an explicit
portability change.

## 11. Handoff and completion checklist

- [ ] Record the target context, versions, node pool and storage/reclaim behavior.
- [ ] Record source revision/release and the three deployed image digests.
- [ ] Foundation: Ready pods, Bound PVC, actual hypertable and passing live SQL checks.
- [ ] Analysis: fresh detector, three SOP originals, 16 indexed sections, two models.
- [ ] Confirm warning/escalation/recovery and persistent acknowledgement/history.
- [ ] Generate a diagnosis from each selected model if both will be demonstrated.
- [ ] Read the outputs critically; keep 14B available and do not claim model certification.
- [ ] Verify preservation baselines and the separate warranty URL if installed.
- [ ] Refresh expiring pull credentials before a later reschedule or demo.
- [ ] Keep source/docs/image metadata, but never hand off `.local` Azure tokens,
      kubeconfig or live Secret values as part of the source package.

Closing the browser or its tunnels does not stop simulation or storage growth.
There is deliberately no `delete namespace` cleanup recipe: the database PVC
may use a `Delete` reclaim policy, and no automated backups exist. Arrange an
approved, targeted decommission/recovery procedure instead.
