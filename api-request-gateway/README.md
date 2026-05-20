# API Request Gateway (`api-request-gateway`)

Production-ready REST API для асинхронного анализа студенческого кода и генерации учебных задач с «битым» кодом. Подходит для публикации в репозитории и деплоя в Docker / Kubernetes.

## Возможности

- **Три режима**: анализ (`/api/v1/analyze`), генерация (`/api/v1/generate`), связка analyze→generate (`/api/v1/pipeline`).
- **Фоновые GPU-воркеры** (Redis Streams), **кэш** результатов (TTL 24 ч), **PostgreSQL** для истории, **webhook + polling** по `task_id`.
- **API-ключи платформ**, **rate limit** на ключ, **OpenAPI** (`/docs`, при `DOCS_ENABLED=true`).
- **Health**: `GET /health/live` (liveness), `GET /health/ready` (readiness: Redis + PostgreSQL).

Стек: FastAPI, Uvicorn, Redis Streams, PostgreSQL, Nginx, Transformers + bitsandbytes, Docker Compose / Kubernetes.

## Быстрый старт (Docker Compose)

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

Публичная точка входа: **https://api.example.com**

- Swagger: https://api.example.com/docs (если `DOCS_ENABLED=true`)  
- Liveness: https://api.example.com/health/live  
- Readiness: https://api.example.com/health/ready  

Заголовок для API: **`X-API-Key`**. В таблице `platforms.api_key` хранится **SHA-256 хэш** ключа,
а не сам ключ. Для локального seed-примера в `001_schema.sql` захэширован ключ `dev-api-key`;
в продакшене создайте новый ключ, сохраните только его хэш и не публикуйте исходное значение.

Пример запроса:

```http
POST /api/v1/analyze
X-API-Key: dev-api-key
Content-Type: application/json

{"student_id":"<uuid>","task_description":"...","code":"...","webhook_url":"https://..."}
```

## Без GPU

Сервисы `worker_*` объявлены с `gpus: all`. На хосте **без** NVIDIA Container Toolkit запуск может завершиться ошибкой.

- **Вариант A**: удалите блок `gpus: all` у воркеров в `docker-compose.override.yml` — инференс пойдёт на CPU (очень медленно).
- **Вариант B**: поднимайте только edge-стек: `nginx`, `gateway_a`, `gateway_b`, `redis`, `postgres`, а воркеры выносите на GPU-ноды с тем же Redis и PostgreSQL.

## Переменные окружения

См. **[.env.example](.env.example)**. Кратко:

| Переменная | Назначение |
|------------|------------|
| `REDIS_URL` | Подключение Redis |
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `RATE_LIMIT_PER_HOUR` | Лимит запросов на API-ключ |
| `CACHE_TTL_SECONDS` | TTL кэша (сек), по умолчанию 86400 |
| `DOCS_ENABLED` | `true` / `false` — Swagger/ReDoc |
| `CORS_ORIGINS` | Список доверенных origin через запятую |
| `WEBHOOK_ALLOWED_HOSTS` | Необязательный allowlist доменов для webhook-доставки |
| `CODE_ANALYZE_MODEL_ID` / `BROKEN_CODE_MODEL_ID` | Идентификаторы моделей в Hugging Face Hub |
| `HF_TOKEN` | Если модели или веса требуют авторизации |

Версия в JSON health: **`APP_VERSION`**.

## Архитектура (кратко)

- **Трафик**: Nginx → два экземпляра Gateway (stateless) → Redis и PostgreSQL.
- **ML**: воркеры читают **Redis Streams** (`queue:analyze`, `queue:generate`, `queue:pipeline`), модель загружается **один раз** при старте процесса.
- **Полный цикл пользователя**: `/pipeline` анализирует решение, обновляет `student_profile` в Redis и генерирует следующую задачу по слабым тегам.

Продакшен-топология: два физических кластера. **Edge** содержит Ingress, edge-balancer и API Gateway. **ML/GPU** содержит Redis, PostgreSQL и GPU workers. Отдельные HTTP ML-сервисы, `auth-service`, `ml-balancer`, SQS-workers и старый корневой Compose больше не являются каноническим контуром.

## Продакшен-чеклист

1. Уникальные пароли БД и API-ключи платформ; хранить только SHA-256 хэши API-ключей.  
2. Не публиковать PostgreSQL/Redis в интернет; держать их только во внутренней сети/кластере.  
3. `DOCS_ENABLED=false`, TLS на reverse-proxy перед Nginx.  
4. Ограничить `CORS_ORIGINS` и `WEBHOOK_ALLOWED_HOSTS`.  
5. Бэкапы PostgreSQL, мониторинг Redis памяти и времени ответа `/health/ready`.  
6. См. [SECURITY.md](SECURITY.md) для ответственного раскрытия уязвимостей.

## Разработка

Требуется [uv](https://docs.astral.sh/uv/) и Python 3.12+.

```bash
uv sync --all-groups
uv run ruff check gateway workers models db tests
uv run ruff check ../libs/edu_ml_common/edu_ml --target-version py312 --line-length 120
uv run pytest
uv run python -m compileall -q gateway workers models db tests
```

Обновление зависимостей: правки в `pyproject.toml`, затем `uv lock` (в репозиторий коммитится **`uv.lock`**).

**CI** — в корне репозитория файл `.github/workflows/ci.yml` (рабочая директория сервиса: `api-request-gateway`): **ruff**, **pytest**, **compileall**, проверочная сборка Docker.

**CD** — `.github/workflows/cd.yml`: push в `main`/`master`, тег `v*` или вручную — образ в **GHCR** (`ghcr.io/<org>/<repo>`).

**Kubernetes** — целевая топология продакшена: **ровно два кластера**. `.github/workflows/deploy-k8s.yml`: сначала кластер **ML** (`kubectl kustomize deploy/k8s/clusters/ml | apply`), затем **edge** (`deploy/k8s/clusters/edge`). В `deploy/k8s/` нет корневой сборки монолита; общие YAML — только в `deploy/k8s/manifests/` без `kustomization.yaml`. Триггеры: изменения в `deploy/k8s/**`, успешный прогон **CD**, либо ручной *workflow_dispatch*. Секреты репозитория или сред: **`KUBECONFIG_ML`**, **`KUBECONFIG_EDGE`** (полный kubeconfig). Опционально среды **k8s-ml** / **k8s-edge** и переменные **`K8S_ML_URL`**, **`K8S_EDGE_URL`**.

## Лицензия

[MIT](LICENSE)
