# Kubernetes (`deploy/k8s/`)

## Канонические overlays для CPU-test

| Overlay | Назначение |
|---------|------------|
| [`clusters/edge/`](k8s/clusters/edge/) | **Edge-кластер:** gateway, webhook-dispatcher, ingress, cross-cluster Endpoints → ML |
| [`clusters/ml-cpu-internal/`](k8s/clusters/ml-cpu-internal/) | **ML-кластер:** redis, postgres, **worker-mock** |
| [`clusters/cpu-test/`](k8s/clusters/cpu-test/) | **Single-cluster:** всё на одном кластере (`edge-with-data`) |

## Data tier и GPU (справочно)

| Overlay | Назначение |
|---------|------------|
| [`clusters/ml-data-only/`](k8s/clusters/ml-data-only/) | Только redis + postgres (без workers) |
| [`clusters/edge-with-data/`](k8s/clusters/edge-with-data/) | Edge + data + mock worker (база для cpu-test) |
| [`overlays/cpu-gpu-topology/`](k8s/overlays/cpu-gpu-topology/) | GPU-воркеры (не используется на CPU-test) |
| [`overlays/gpu-pool-rtx4090-rtx4060/`](k8s/overlays/gpu-pool-rtx4090-rtx4060/) | Пулы GPU (справочно) |

## Two-cluster (Edge + ML)

1. Edge и ML — **одна private-сеть** (один VPC / subnet).
2. ML: `kubectl apply -k deploy/k8s/clusters/ml-cpu-internal`
3. Edge: overlay с IP ML-ноды (NodePort redis **30637**, postgres **30432**).
4. Ingress-nginx на Edge; публичный доступ через Load Balancer или EXTERNAL-IP сервиса.

Подробные шаги деплоя и секреты — в локальной папке `local/` (не в git).

## Общие манифесты

Базовые ресурсы: [`k8s/manifests/`](k8s/manifests/) (gateway, redis, postgres, workers, network policies).

## CI

Workflow [`.github/workflows/cpu-test.yml`](../.github/workflows/cpu-test.yml): ruff, pytest, kustomize validate, push образа в GHCR.
