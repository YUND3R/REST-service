# REST

REST API для асинхронного разбора студенческого кода и генерации учебных задач. Gateway на FastAPI, очереди Redis Streams, история в PostgreSQL, деплой в Kubernetes.

На ветке **CPU-test** я проверяю систему **без GPU**: вместо тяжёлых моделей работают **mock worker** (см. [mock-worker/README.md](mock-worker/README.md)) — ответы по форме как у боевых воркеров, но без inference.

![CI CPU-test](https://github.com/yund3r/rest-service/actions/workflows/cpu-test.yml/badge.svg?branch=CPU-test)

## Что где лежит

- **api-request-gateway/** — сам сервис: API, workers, тесты, Docker
- **deploy/k8s/** — манифесты и overlays для Kubernetes ([deploy/README.md](deploy/README.md))
- **mock-worker/** — пояснение про mock worker и заготовки под веса (не для текущего CPU-деплоя)
- **legacy/** — старая архитектура, для справки
- **local/** — kubeconfig, скрипты, секреты (в git не коммитится)

## Kubernetes

Основной вариант для апробации — **два кластера**: Edge (gateway, ingress) и ML (redis, postgres, mock worker) в одной private-сети. Overlays: `deploy/k8s/clusters/edge/` и `deploy/k8s/clusters/ml-cpu-internal/`.

Если нужно всё на одном кластере — `deploy/k8s/clusters/cpu-test/`.

Подробнее про overlays — в [deploy/README.md](deploy/README.md). API и разработка — в [api-request-gateway/README.md](api-request-gateway/README.md).

## Локальная разработка

```bash
cd api-request-gateway
uv sync --all-groups
uv run pytest
```

Зависимости фиксируются в `uv.lock`.

Лицензия: MIT ([api-request-gateway/LICENSE](api-request-gateway/LICENSE)).
