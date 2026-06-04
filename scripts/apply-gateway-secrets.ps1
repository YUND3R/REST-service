# Create gateway-secrets on ML and Edge (password from .env or existing ML postgres-secrets).
param(
    [ValidateSet("ml", "edge", "both")]
    [string]$Cluster = "both",
    [string]$EnvFile = "",
    [string]$MlKubeconfig = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $MlKubeconfig) { $MlKubeconfig = Join-Path $Root "llm.yaml" }
if (-not $EnvFile) {
    $EnvFile = Join-Path $Root "CPU-deploy for test\.env"
}

$vars = @{}
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
        $k, $v = $_ -split '=', 2
        $vars[$k.Trim()] = $v.Trim()
    }
}

$pgPass = $vars["POSTGRES_PASSWORD"]
$webhook = $vars["WEBHOOK_SIGNING_SECRET"]

if (-not $pgPass -and (Test-Path $MlKubeconfig)) {
    $prev = $env:KUBECONFIG
    $env:KUBECONFIG = $MlKubeconfig
    $b64 = kubectl -n edu-ml get secret postgres-secrets -o jsonpath='{.data.password}' 2>$null
    $env:KUBECONFIG = $prev
    if ($b64) {
        $pgPass = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
    }
}

if (-not $webhook -and (Test-Path $MlKubeconfig)) {
    $prev = $env:KUBECONFIG
    $env:KUBECONFIG = $MlKubeconfig
    $b64 = kubectl -n edu-ml get secret gateway-secrets -o jsonpath='{.data.webhook-signing-secret}' 2>$null
    $env:KUBECONFIG = $prev
    if ($b64) {
        $webhook = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
    }
}

if ($pgPass -in @("", "change-me")) { $pgPass = $null }
if ($webhook -in @("", "change-me-too")) { $webhook = $null }

if (-not $pgPass) {
    throw "Set POSTGRES_PASSWORD in $EnvFile (not change-me)."
}
if (-not $webhook) {
    throw "Set WEBHOOK_SIGNING_SECRET in $EnvFile."
}

$dbUrl = "postgresql+asyncpg://ai_mentor:${pgPass}@postgres:5432/ai_mentor"

function Apply-Secret {
    param([string]$Kubeconfig)
    $env:KUBECONFIG = $Kubeconfig
    kubectl create namespace edu-ml --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n edu-ml delete secret gateway-secrets postgres-secrets --ignore-not-found 2>$null
    kubectl -n edu-ml create secret generic postgres-secrets --from-literal=password=$pgPass
    kubectl -n edu-ml create secret generic gateway-secrets `
        --from-literal=database-url=$dbUrl `
        --from-literal=webhook-signing-secret=$webhook
    Write-Host "gateway-secrets on $(Split-Path -Leaf $Kubeconfig)"
}

if ($Cluster -in @("ml", "both")) {
    Apply-Secret $MlKubeconfig
}
if ($Cluster -in @("edge", "both")) {
    Apply-Secret (Join-Path $Root "abigail.yaml")
}
