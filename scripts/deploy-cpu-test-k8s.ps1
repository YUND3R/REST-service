# Deploy ML data tier and Edge API (edge-with-data overlay).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$MlKube = Join-Path $Root "llm.yaml"
$EdgeKube = Join-Path $Root "abigail.yaml"
$MlHostFile = Join-Path $Root "deploy\k8s\clusters\edge\files\ml-node-host.env"
$EdgeOverlay = Join-Path $Root "deploy\k8s\clusters\edge-with-data"

function Require-Path($p, $hint) {
    if (-not (Test-Path $p)) { throw "Missing: $p. $hint" }
}

Require-Path $MlKube "Download kubeconfig for ML cluster"
Require-Path $EdgeKube "Download kubeconfig for Edge cluster"
Require-Path (Join-Path $Root "certs\ca.crt") "Run: .\scripts\generate-k8s-tls-certs-docker.ps1"
Require-Path (Join-Path $Root "CPU-deploy for test\.env") "Create CPU-deploy for test\.env from scripts\cpu-test-k8s.env.example"

$env:KUBECONFIG = $MlKube
$mlIp = (kubectl get nodes -o wide --no-headers | Select-Object -First 1).ToString().Trim() -split '\s+' | Select-Object -Index 5
"ML_NODE_HOST=$mlIp" | Set-Content -Path $MlHostFile -Encoding ascii
Write-Host "ML internal tier, node IP: $mlIp"

Write-Host "`n[1/4] ML cluster (redis, postgres, workers=0)..."
& (Join-Path $Root "scripts\apply-k8s-tls-secrets.ps1") -Cluster ml -Kubeconfig $MlKube
& (Join-Path $Root "scripts\apply-gateway-secrets.ps1") -Cluster ml
kubectl kustomize (Join-Path $Root "deploy\k8s\clusters\ml") --load-restrictor LoadRestrictionsNone | kubectl apply -f -
kubectl -n edu-ml rollout status deployment/redis deployment/postgres --timeout=180s

Write-Host "`n[2/4] Edge cluster (API + local redis/postgres for CPU-test)..."
& (Join-Path $Root "scripts\apply-k8s-tls-secrets.ps1") -Cluster edge -Kubeconfig $EdgeKube
& (Join-Path $Root "scripts\apply-gateway-secrets.ps1") -Cluster edge
$env:KUBECONFIG = $EdgeKube
kubectl kustomize $EdgeOverlay --load-restrictor LoadRestrictionsNone | kubectl apply -f -
kubectl -n edu-ml rollout status deployment/redis deployment/postgres deployment/gateway deployment/edge-balancer --timeout=300s

Write-Host "`n[3/4] Ingress TLS (cpu-test2clusteres.ru)..."
& (Join-Path $Root "scripts\update-ingress-tls.ps1") -Kubeconfig $EdgeKube
kubectl kustomize $EdgeOverlay --load-restrictor LoadRestrictionsNone | kubectl apply -f -
$env:KUBECONFIG = $EdgeKube
kubectl -n edu-ml rollout restart deployment/redis deployment/postgres deployment/gateway
kubectl -n edu-ml rollout status deployment/redis deployment/postgres deployment/gateway --timeout=300s
$env:KUBECONFIG = $MlKube
kubectl -n edu-ml rollout restart deployment/redis deployment/postgres
kubectl -n edu-ml rollout status deployment/redis deployment/postgres --timeout=180s

Write-Host "`n[4/4] Cleanup test pods..."
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
kubectl -n edu-ml delete pod nettest-reach xcluster-test xc-verify --ignore-not-found 2>$null | Out-Null
$ErrorActionPreference = $prev

try { & (Join-Path $Root "scripts\trust-edu-ml-ca.ps1") } catch { Write-Host "CA trust skipped (run as Admin): .\scripts\trust-edu-ml-ca.ps1" }

& (Join-Path $Root "scripts\verify-cpu-test.ps1")
