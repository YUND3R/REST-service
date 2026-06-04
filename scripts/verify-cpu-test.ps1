# Post-deploy health check (ML + Edge).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$MlKube = Join-Path $Root "llm.yaml"
$EdgeKube = Join-Path $Root "abigail.yaml"
$ok = $true

function Test-Cluster {
    param([string]$Name, [string]$Kube, [string[]]$MustRun)
    $env:KUBECONFIG = $Kube
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    $pods = kubectl -n edu-ml get pods --no-headers 2>$null
    if (-not $pods) { Write-Host "FAIL: no pods"; return $false }
    $bad = @()
    foreach ($p in $MustRun) {
        $line = kubectl -n edu-ml get pods -l "app=$p" --no-headers 2>$null
        if ($line -match "Running") { Write-Host "OK  $p" }
        else { $bad += $p; Write-Host "FAIL $p : $line" -ForegroundColor Red }
    }
    if ($bad) { return $false }
    return $true
}

if (-not (Test-Cluster -Name "ML (internal data tier)" -Kube $MlKube -MustRun @("redis", "postgres"))) {
    $ok = $false
}
if (-not (Test-Cluster -Name "Edge (public API)" -Kube $EdgeKube -MustRun @("gateway", "edge-balancer", "redis", "postgres"))) {
    $ok = $false
}

$env:KUBECONFIG = $EdgeKube
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ready = kubectl -n edu-ml exec deploy/gateway -- python -c "import asyncio; from db.session import ping_database; print('db', asyncio.run(ping_database()))" 2>&1
$redis = kubectl -n edu-ml exec deploy/gateway -- python -c "import asyncio,redis.asyncio as r; import os; c=r.from_url(os.environ['REDIS_URL'], decode_responses=True); asyncio.run(c.ping()); print('redis ok')" 2>&1
$ErrorActionPreference = $prev
Write-Host "`n=== Gateway connectivity ===" -ForegroundColor Cyan
if ($ready -match "db True") { Write-Host "OK  Postgres" } else { Write-Host "FAIL Postgres: $ready"; $ok = $false }
if ($redis -match "redis ok") { Write-Host "OK  Redis" } else { Write-Host "FAIL Redis: $redis"; $ok = $false }

$env:KUBECONFIG = $EdgeKube
$mlIp = (Get-Content (Join-Path $Root "deploy\k8s\clusters\edge\files\ml-node-host.env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "ML_NODE_HOST=" }) -replace "ML_NODE_HOST=", ""
if ($mlIp) {
    $ErrorActionPreference = "Continue"
    $xc = kubectl -n edu-ml run xc-verify --rm -i --restart=Never --image=busybox:1.36 --command -- sh -c "nc -z -w 3 $mlIp 30637" 2>&1 | Out-String
    $ErrorActionPreference = $prev
    if ($xc -match "open|succeeded") {
        Write-Host "`nOK  Edge->ML NodePort (cross-cluster possible)" -ForegroundColor Green
    } else {
        Write-Host "`n--  Edge->ML NodePort unreachable (using data tier on Edge)" -ForegroundColor Yellow
    }
}

$ip = kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
Write-Host "`n=== URLs ===" -ForegroundColor Cyan
Write-Host "Swagger: https://cpu-test2clusteres.ru/docs  (DNS/hosts -> $ip)"
Write-Host "API key: dev-api-key"

if ($ok) { Write-Host "`nAll checks passed" -ForegroundColor Green }
else { Write-Host "`nSome checks failed" -ForegroundColor Red; exit 1 }
