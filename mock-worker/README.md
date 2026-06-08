# mock-worker

В этом проекте на ветке CPU-test я **не гоняю настоящие нейросети**. Вместо GPU-моделей стоят **mock worker** — они имитируют ответы analyze/generate/pipeline, чтобы можно было проверить весь REST-контур: API, очередь в Redis, Postgres, webhook, деплой в Kubernetes. Для диплома и тестов на Selectel этого достаточно, а кластер обходится без видеокарт.

Сам код mock worker лежит в `api-request-gateway/workers/mock_workers.py`. В Kubernetes он поднимается через overlay `deploy/k8s/clusters/ml-cpu-internal/` (ML-кластер: redis, postgres и worker-mock).

Папки `code-analyze/` и `task-generate/` здесь почти пустые — это заготовки под **локальные веса** моделей, если когда-нибудь понадобится старый GPU-стек из `legacy/`. В git они не попадают (только `.gitkeep`). Для обычного CPU-деплоя их можно не трогать.

Не путать с `api-request-gateway/models/` — там Python-код inference, а не файлы моделей с диска.
