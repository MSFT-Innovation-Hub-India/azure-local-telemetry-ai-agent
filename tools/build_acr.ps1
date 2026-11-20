param(
    [Parameter(Mandatory = $true)][string]$Registry,
    [Parameter(Mandatory = $true)][string]$AzureConfigDir,
    [switch]$SimulatorOnly,
    [switch]$AppOnly,
    [string]$Tag = ("telemetry-" + (Get-Date -Format "yyyyMMddHHmmss"))
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$previousConfig = $env:AZURE_CONFIG_DIR
$env:AZURE_CONFIG_DIR = (Resolve-Path $AzureConfigDir).Path
Push-Location $root
try {
    if ($AppOnly -and $SimulatorOnly) { throw 'Choose AppOnly or SimulatorOnly, not both.' }
    $server = az acr show --name $Registry --query loginServer -o tsv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot access the approved registry.' }
    $component = 'simulator'
    if ($AppOnly) { $component = 'app' }
    az acr build --registry $Registry --file Dockerfile `
        --image "ssrikantan/realtime-telemetry/${component}:$Tag" `
        --platform linux/amd64 --no-logs --output none .
    if ($LASTEXITCODE -ne 0) { throw "$component image build failed." }
    if (-not ($SimulatorOnly -or $AppOnly)) {
        az acr import --name $Registry `
            --source "docker.io/timescale/timescaledb@sha256:6a6b7d7a346d7c6be03a310c240706f3bbc6d7adbdf3fbc07823570b34337f5e" `
            --image "ssrikantan/realtime-telemetry/timescaledb:$Tag"
        if ($LASTEXITCODE -ne 0) { throw 'Upstream TimescaleDB image import failed.' }
    }
    $componentDigest = az acr repository show --name $Registry `
        --image "ssrikantan/realtime-telemetry/${component}:$Tag" --query digest -o tsv
    if ($LASTEXITCODE -ne 0) { throw "Cannot resolve $component digest." }
    $previous = $null
    if (Test-Path .local\images.json) { $previous = Get-Content -Raw .local\images.json | ConvertFrom-Json }
    if ($SimulatorOnly -or $AppOnly) {
        if (-not $previous) { throw 'An existing image manifest is required for a component-only build.' }
        if ($previous.registry -ne $Registry -or $previous.server -ne $server) {
            throw 'Component-only build must use the existing registry.'
        }
        $databaseImage = $previous.database_image
    }
    else {
        $databaseDigest = az acr repository show --name $Registry `
            --image "ssrikantan/realtime-telemetry/timescaledb:$Tag" --query digest -o tsv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve database digest.' }
        $databaseImage = "$server/ssrikantan/realtime-telemetry/timescaledb@$databaseDigest"
    }
    $images = @{
        registry = $Registry
        server = $server
        simulator_image = "$server/ssrikantan/realtime-telemetry/simulator@$componentDigest"
        database_image = $databaseImage
    }
    if ($AppOnly) {
        $images.simulator_image = $previous.simulator_image
        $images.app_image = "$server/ssrikantan/realtime-telemetry/app@$componentDigest"
    }
    elseif ($previous -and $previous.app_image) { $images.app_image = $previous.app_image }
    $images = $images | ConvertTo-Json
    New-Item -ItemType Directory -Force .local | Out-Null
    $images | Set-Content -Encoding ascii .local\images.json
    Write-Output $images
}
finally {
    Pop-Location
    $env:AZURE_CONFIG_DIR = $previousConfig
}
