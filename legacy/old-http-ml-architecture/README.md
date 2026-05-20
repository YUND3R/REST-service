# Legacy HTTP ML Architecture

Эта папка хранит старую архитектуру как архив и референс. Она не является каноническим
продакшен-контуром проекта.

## Что здесь было

- `auth-service` как отдельный HTTP-сервис.
- `code-analyze` как отдельный HTTP ML-сервис.
- `task-generate` как отдельный HTTP ML-сервис.
- `redis-analyze` и `redis-generate` как две отдельные Redis-инстанции.
- `ml-balancer` как HTTP-router внутри ML-кластера.
- SQS worker-профиль для отдельных ML-сервисов.
- Terraform для старых SQS/S3 контуров.
- Старые root-level `requirements.*`, `.env.example` и заметки по локальным путям моделей.

## Почему вынесено в legacy

Новая архитектура проще и чище:

- Edge/API кластер: `Ingress -> edge-balancer -> API Gateway`.
- ML/GPU кластер: `Redis Streams + PostgreSQL + worker-analyze + worker-generate + worker-pipeline`.
- Gateway больше не вызывает ML-сервисы по HTTP, а кладёт задачи в Redis Streams.

## Что использовать сейчас

Для продакшена используйте:

- `deploy/k8s/clusters/edge`
- `deploy/k8s/clusters/ml`
- `api-request-gateway/docker-compose.yml` для локального запуска.

Файлы в этой папке нужны только для истории, сравнения или ручного восстановления старой схемы.

## Состав папки

- `services/` — старые отдельные HTTP-сервисы и SQS workers.
- `k8s/manifests/` — старые manifest-фрагменты для HTTP ML, `ml-balancer`, `auth-service`, двух Redis.
- `k8s/overlays/` — старые overlay для mTLS/direct LB и legacy GPU/auth patches.
- `terraform/` — старые SQS/S3 заготовки.
- `docker-compose.yml` — старый локальный запуск отдельного ML-контура.
