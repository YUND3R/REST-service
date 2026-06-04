# Create K8s TLS secrets from ./certs (run after generate-k8s-tls-certs-docker.ps1).
param(
    [ValidateSet("ml", "edge")]
    [string]$Cluster = "ml",
    [string]$Kubeconfig = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($Kubeconfig) { $env:KUBECONFIG = $Kubeconfig }
$Certs = Join-Path $Root "certs"

function Require-File($path) {
    if (-not (Test-Path $path)) {
        throw "Missing file: $path. Run: .\scripts\generate-k8s-tls-certs-docker.ps1"
    }
}

kubectl create namespace edu-ml --dry-run=client -o yaml | kubectl apply -f -

if ($Cluster -eq "ml") {
    $ca = Join-Path $Certs "ca.crt"
    $pgCrt = Join-Path $Certs "postgres-tls.crt"
    $pgKey = Join-Path $Certs "postgres-tls.key"
    $rdCrt = Join-Path $Certs "redis-tls.crt"
    $rdKey = Join-Path $Certs "redis-tls.key"
    Require-File $ca
    Require-File $pgCrt
    Require-File $pgKey
    Require-File $rdCrt
    Require-File $rdKey

    kubectl -n edu-ml delete secret postgres-tls redis-tls --ignore-not-found
    kubectl -n edu-ml create secret generic postgres-tls `
        "--from-file=ca.crt=$ca" `
        "--from-file=tls.crt=$pgCrt" `
        "--from-file=tls.key=$pgKey"
    kubectl -n edu-ml create secret generic redis-tls `
        "--from-file=ca.crt=$ca" `
        "--from-file=tls.crt=$rdCrt" `
        "--from-file=tls.key=$rdKey"
    Write-Host "ML TLS secrets: postgres-tls, redis-tls"
}

if ($Cluster -eq "edge") {
    $ca = Join-Path $Certs "ca.crt"
    $rdCliCrt = Join-Path $Certs "redis-client-tls.crt"
    $rdCliKey = Join-Path $Certs "redis-client-tls.key"
    $pgCliCrt = Join-Path $Certs "postgres-client-tls.crt"
    $pgCliKey = Join-Path $Certs "postgres-client-tls.key"
    $apiCrt = Join-Path $Certs "api.crt"
    $apiKey = Join-Path $Certs "api.key"
    Require-File $ca
    Require-File $rdCliCrt
    Require-File $rdCliKey
    Require-File $pgCliCrt
    Require-File $pgCliKey
    Require-File $apiCrt
    Require-File $apiKey

    $pgCrt = Join-Path $Certs "postgres-tls.crt"
    $pgKey = Join-Path $Certs "postgres-tls.key"
    $rdCrt = Join-Path $Certs "redis-tls.crt"
    $rdKey = Join-Path $Certs "redis-tls.key"
    Require-File $pgCrt
    Require-File $pgKey
    Require-File $rdCrt
    Require-File $rdKey

    kubectl -n edu-ml delete secret redis-client-tls postgres-client-tls redis-tls postgres-tls edu-ml-tls --ignore-not-found
    kubectl -n edu-ml create secret generic redis-client-tls `
        "--from-file=tls.crt=$rdCliCrt" `
        "--from-file=tls.key=$rdCliKey"
    kubectl -n edu-ml create secret generic postgres-client-tls `
        "--from-file=ca.crt=$ca" `
        "--from-file=tls.crt=$pgCliCrt" `
        "--from-file=tls.key=$pgCliKey"
    kubectl -n edu-ml create secret generic postgres-tls `
        "--from-file=ca.crt=$ca" `
        "--from-file=tls.crt=$pgCrt" `
        "--from-file=tls.key=$pgKey"
    kubectl -n edu-ml create secret generic redis-tls `
        "--from-file=ca.crt=$ca" `
        "--from-file=tls.crt=$rdCrt" `
        "--from-file=tls.key=$rdKey"
    $fullchain = Join-Path $Certs "api-fullchain.crt"
    Get-Content $apiCrt, $ca | Set-Content -Path $fullchain -Encoding ascii
    kubectl -n edu-ml create secret tls edu-ml-tls "--cert=$fullchain" "--key=$apiKey"
    Write-Host "Edge TLS secrets: redis-client-tls, postgres-client-tls, redis-tls, postgres-tls, edu-ml-tls"
}

kubectl -n edu-ml get secrets
