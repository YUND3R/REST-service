# Regenerate Ingress TLS cert (SAN: api.example.com + public LB IP) and apply to Edge.
param(
    [string]$IngressHost = "cpu-test2clusteres.ru",
    [string]$Kubeconfig = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Kubeconfig) { $Kubeconfig = Join-Path $Root "abigail.yaml" }
if (-not (Test-Path $Kubeconfig)) { throw "Missing kubeconfig: $Kubeconfig" }

$env:KUBECONFIG = $Kubeconfig
$ip = kubectl -n edu-ml get ingress edu-ml-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
if (-not $ip) {
    $ip = kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
}
if (-not $ip) { throw "Could not detect Ingress public IP" }

$env:INGRESS_HOST = $IngressHost
$env:INGRESS_IP = $ip
Write-Host "Ingress TLS: host=$IngressHost ip=$ip"

& (Join-Path $Root "scripts\generate-k8s-tls-certs-docker.ps1")
$MlKube = Join-Path $Root "llm.yaml"
if (Test-Path $MlKube) {
    & (Join-Path $Root "scripts\apply-k8s-tls-secrets.ps1") -Cluster ml -Kubeconfig $MlKube
}
& (Join-Path $Root "scripts\apply-k8s-tls-secrets.ps1") -Cluster edge -Kubeconfig $Kubeconfig

Write-Host ""
Write-Host "HTTPS URLs:"
Write-Host "  https://${ip}/docs"
Write-Host "  https://${IngressHost}/docs  (DNS A ${ip} or hosts: ${ip} ${IngressHost})"
Write-Host "Trust CA once: import $Root\certs\ca.crt into Trusted Root Certification Authorities"
