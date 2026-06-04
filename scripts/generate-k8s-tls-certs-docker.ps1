# Generate certs using Docker (no local OpenSSL required).
# Requires Docker Desktop running.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "certs"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$dockerEnv = @()
if ($env:INGRESS_HOST) { $dockerEnv += "-e", "INGRESS_HOST=$($env:INGRESS_HOST)" }
if ($env:INGRESS_IP) { $dockerEnv += "-e", "INGRESS_IP=$($env:INGRESS_IP)" }

docker run --rm @dockerEnv -v "${Root}:/work" -w /work alpine:3.20 `
  sh -c "apk add --no-cache openssl bash >/dev/null && sed -i 's/\r$//' scripts/generate-k8s-tls-certs.sh && bash scripts/generate-k8s-tls-certs.sh"
if ($LASTEXITCODE -ne 0) {
  throw "Certificate generation failed. Is Docker Desktop running?"
}
Write-Host "Certificates written to $Out"
