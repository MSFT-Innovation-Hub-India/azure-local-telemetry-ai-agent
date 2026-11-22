<#
.SYNOPSIS
    Brings up laptop access to the telemetry demo: Arc proxy, kubectl context and port-forward.

.DESCRIPTION
    1. Selects the kubectl context for the cluster.
    2. Starts `az connectedk8s proxy` unless the cluster is already reachable (an existing
       proxy is reused and never stopped by this script).
    3. Port-forwards telemetry-web (and optionally the warranty assistant) to localhost.
    4. Stays in the foreground and restarts a port-forward that exits (for example after an
       app upgrade). Ctrl+C stops only the processes this script started.

    Logs are written to %TEMP%\telemetry-demo-access.

.EXAMPLE
    .\tools\start-demo.ps1
    .\tools\start-demo.ps1 -IncludeWarranty
    .\tools\start-demo.ps1 -TelemetryPort 8091 -NoBrowser
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "zines-22325-rg",
    [string]$ClusterName = "zines-22325-aks",
    [string]$Context = "zines-22325-aks",
    [int]$TelemetryPort = 8090,
    [int]$WarrantyPort = 8080,
    [switch]$IncludeWarranty,
    [switch]$NoBrowser,
    [int]$StartupTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$logDir = Join-Path $env:TEMP "telemetry-demo-access"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$owned = New-Object System.Collections.Generic.List[object]
$script:proxy = $null

function Invoke-Quiet([scriptblock]$Command) {
    # Probing a native command that may fail must not turn its stderr into a terminating error.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command 2>$null | Out-Null } finally { $ErrorActionPreference = $previous }
    return $LASTEXITCODE -eq 0
}

function Set-KubeContext {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $names = @(kubectl config get-contexts -o name 2>$null) } finally { $ErrorActionPreference = $previous }
    if ($names -notcontains $Context) { return $false }
    return Invoke-Quiet { kubectl config use-context $Context }
}

function Test-Cluster {
    return Invoke-Quiet { kubectl --context $Context --request-timeout=10s get namespace telemetry-demo -o name }
}

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $Port); return $true } catch { return $false } finally { $client.Close() }
}

function Show-Log([string]$Path) {
    if (Test-Path $Path) { Get-Content $Path -Tail 15 | ForEach-Object { Write-Host "  $_" } }
}

function Start-Forward($Forward) {
    $log = Join-Path $logDir ("forward-{0}.log" -f $Forward.Port)
    $kubectlArgs = @("--context", $Context, "-n", $Forward.Namespace, "port-forward", "svc/$($Forward.Service)",
              "--address", "127.0.0.1", "$($Forward.Port):80")
    $Forward.Process = Start-Process kubectl -ArgumentList $kubectlArgs -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError ($log + ".err")
    $Forward.Log = $log + ".err"
    $Forward.Started = Get-Date
}

function Start-ArcProxy {
    if (-not (Invoke-Quiet { az account show --query id -o tsv })) { throw "Not signed in to Azure. Run 'az login' first." }
    Write-Host "Starting Arc proxy for $ClusterName in $ResourceGroup ..."
    $proxyLog = Join-Path $logDir "proxy.log"
    $item = [pscustomobject]@{ Process = $null }
    $item.Process = Start-Process az -ArgumentList @("connectedk8s", "proxy", "--resource-group", $ResourceGroup, "--name", $ClusterName) `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput $proxyLog -RedirectStandardError ($proxyLog + ".err")
    $owned.Add($item)
    $script:proxy = $item
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($item.Process.HasExited) {
            Show-Log $proxyLog; Show-Log ($proxyLog + ".err")
            throw "The Arc proxy exited before the cluster became reachable."
        }
        if ((Set-KubeContext) -and (Test-Cluster)) { Write-Host "Arc proxy is ready."; return }
        Start-Sleep -Seconds 3
    }
    throw "Cluster not reachable through the Arc proxy within $StartupTimeoutSeconds seconds (see $proxyLog)."
}

function Wait-Forward($Forward) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if ($Forward.Process.HasExited) { break }
        if (Test-Port $Forward.Port) { return }
        Start-Sleep -Seconds 1
    }
    Show-Log $Forward.Log
    throw "Port-forward to $($Forward.Service) on port $($Forward.Port) did not become ready."
}

function Stop-Owned {
    foreach ($item in $owned) {
        if ($item.Process -and -not $item.Process.HasExited) { [void](Invoke-Quiet { taskkill /PID $item.Process.Id /T /F }) }
    }
}

try {
    foreach ($tool in "kubectl", "az") {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool was not found on PATH." }
    }
    $busy = @($TelemetryPort) + $(if ($IncludeWarranty) { @($WarrantyPort) } else { @() }) | Where-Object { Test-Port $_ }
    if ($busy) {
        throw "Local port(s) $($busy -join ', ') already in use. Reuse the existing tunnel or choose another port (-TelemetryPort / -WarrantyPort)."
    }

    [void](Set-KubeContext)
    if (Test-Cluster) {
        Write-Host "Cluster already reachable through context '$Context'; reusing the existing Arc proxy."
    } else {
        Start-ArcProxy
    }

    $forwards = @([pscustomobject]@{ Name = "Telemetry"; Namespace = "telemetry-demo"; Service = "telemetry-web"; Port = $TelemetryPort; Process = $null; Log = $null; Started = $null; Failures = 0 })
    if ($IncludeWarranty) {
        $forwards += [pscustomobject]@{ Name = "Warranty assistant"; Namespace = "assistant-demo"; Service = "assistant-web"; Port = $WarrantyPort; Process = $null; Log = $null; Started = $null; Failures = 0 }
    }
    foreach ($forward in $forwards) {
        Start-Forward $forward
        $owned.Add($forward)
        Wait-Forward $forward
        Write-Host ("{0,-20} http://127.0.0.1:{1}" -f $forward.Name, $forward.Port)
    }
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$TelemetryPort" }
    Write-Host "Demo access is up. Press Ctrl+C to stop the processes started by this script."

    while ($true) {
        Start-Sleep -Seconds 5
        $ended = @($forwards | Where-Object { $_.Process.HasExited })
        $proxyEnded = $script:proxy -and $script:proxy.Process.HasExited
        if (-not ($ended.Count -or $proxyEnded)) { continue }
        if (-not (Test-Cluster)) {
            Write-Warning "The cluster is no longer reachable (the Arc proxy stopped); starting a new proxy."
            Start-ArcProxy
        }
        foreach ($forward in $ended) {
            $forward.Failures = if (((Get-Date) - $forward.Started).TotalSeconds -lt 15) { $forward.Failures + 1 } else { 1 }
            if ($forward.Failures -ge 5) {
                Show-Log $forward.Log
                throw "$($forward.Name) port-forward keeps ending even though the cluster is reachable (see $($forward.Log))."
            }
            Write-Warning "$($forward.Name) port-forward ended; restarting."
            Start-Forward $forward
        }
    }
} finally {
    Stop-Owned
}
