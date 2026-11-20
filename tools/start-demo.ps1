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

function Set-KubeContext {
    $names = @(kubectl config get-contexts -o name 2>$null)
    if ($names -notcontains $Context) { return $false }
    kubectl config use-context $Context 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Test-Cluster {
    kubectl --context $Context --request-timeout=10s get namespace telemetry-demo -o name 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
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
        if ($item.Process -and -not $item.Process.HasExited) { taskkill /PID $item.Process.Id /T /F 2>$null | Out-Null }
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
        az account show --query id -o tsv 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Not signed in to Azure. Run 'az login' first." }
        Write-Host "Starting Arc proxy for $ClusterName in $ResourceGroup ..."
        $proxyLog = Join-Path $logDir "proxy.log"
        $proxy = [pscustomobject]@{ Process = $null }
        $proxy.Process = Start-Process az -ArgumentList @("connectedk8s", "proxy", "--resource-group", $ResourceGroup, "--name", $ClusterName) `
            -PassThru -WindowStyle Hidden -RedirectStandardOutput $proxyLog -RedirectStandardError ($proxyLog + ".err")
        $owned.Add($proxy)
        $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
        $ready = $false
        while ((Get-Date) -lt $deadline) {
            if ($proxy.Process.HasExited) {
                Show-Log $proxyLog; Show-Log ($proxyLog + ".err")
                throw "The Arc proxy exited before the cluster became reachable."
            }
            if ((Set-KubeContext) -and (Test-Cluster)) { $ready = $true; break }
            Start-Sleep -Seconds 3
        }
        if (-not $ready) { throw "Cluster not reachable through the Arc proxy within $StartupTimeoutSeconds seconds (see $proxyLog)." }
        Write-Host "Arc proxy is ready."
    }

    $forwards = @([pscustomobject]@{ Name = "Telemetry"; Namespace = "telemetry-demo"; Service = "telemetry-web"; Port = $TelemetryPort; Process = $null; Log = $null })
    if ($IncludeWarranty) {
        $forwards += [pscustomobject]@{ Name = "Warranty assistant"; Namespace = "assistant-demo"; Service = "assistant-web"; Port = $WarrantyPort; Process = $null; Log = $null }
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
        if ($proxy -and $proxy.Process.HasExited) { throw "The Arc proxy exited; re-run this script." }
        foreach ($forward in $forwards) {
            if ($forward.Process.HasExited) {
                Write-Warning "$($forward.Name) port-forward ended; restarting."
                Start-Forward $forward
            }
        }
    }
} finally {
    Stop-Owned
}
