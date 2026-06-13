# Руководство по интеграции API

Документ описывает порядок подключения к API для внешних платформ и команд разработки.
Материал ориентирован на интеграцию на стороне backend и не содержит инфраструктурных деталей.

## 1. Назначение и возможности

Сервис предоставляет единый HTTPS API для следующих сценариев:

- анализ пользовательского кода;
- генерация учебных задач;
- запуск полного пайплайна (анализ + генерация);
- получение статуса асинхронных операций;
- доступ к истории и профилю студента.

Базовый префикс API:

`https://test4rest-service.ru/api/v1`

## 2. Предварительные условия

Для начала интеграции требуются:

1. Серверная часть клиента, способная выполнять HTTPS-запросы.
2. Выданный сервисный ключ `X-API-Key`.
3. Публичный HTTPS webhook endpoint для получения результатов.
4. Логика polling/retry для асинхронных задач.

`X-API-Key` должен храниться только на стороне backend.

## 3. Модель авторизации

Поддерживаются два варианта доступа:

- сервисный: `X-API-Key`;
- пользовательский: `Authorization: Bearer <JWT>`.

Одновременно использовать оба способа в одном запросе нельзя.

### Получение JWT пользователя

1. `POST /auth/register` (сервисный ключ) -> возвращает `user_id` и `access_token`.
2. `POST /auth/token` (сервисный ключ) -> перевыпускает токен по `user_id`.

## 4. Быстрый старт

### 4.1 Проверка доступности

```bash
curl -s "https://test4rest-service.ru/health/ready"
```

Ожидаемый результат: `status=ready`.

### 4.2 Регистрация пользователя

```bash
curl -X POST "https://test4rest-service.ru/api/v1/auth/register" \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d "{}"
```

Пример ответа:

```json
{
  "user_id": "uuid",
  "access_token": "jwt",
  "token_type": "bearer"
}
```

`user_id` необходимо сохранить в системе клиента как внешний идентификатор.

### 4.3 Запуск анализа

```bash
curl -X POST "https://test4rest-service.ru/api/v1/analyze" \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "PUT_USER_ID_HERE",
    "task_description": "Проверка решения",
    "code": "print(1)",
    "webhook_url": "https://your-domain.com/webhooks/ai"
  }'
```

Ответ:

```json
{
  "task_id": "uuid",
  "status": "pending"
}
```

### 4.4 Получение статуса

```bash
curl "https://test4rest-service.ru/api/v1/status/<TASK_ID>" \
  -H "X-API-Key: <YOUR_API_KEY>"
```

Статусы задачи:
- `pending`
- `processing`
- `done`
- `failed`

## 5. Основные endpoints

### Авторизация

- `POST /auth/register`
- `POST /auth/token`

### Асинхронные операции

- `POST /analyze`
- `POST /generate`
- `POST /pipeline`
- `GET /status/{task_id}`

### Данные студента

- `GET /students/{student_id}/history`
- `GET /students/{student_id}/profile`

## 6. Рекомендуемый flow интеграции

1. Пользователь проходит регистрацию/вход на стороне платформы клиента.
2. Backend платформы получает и хранит `user_id`/JWT через `/auth/*`.
3. При пользовательском действии backend отправляет запрос `POST /analyze|generate|pipeline`.
4. Backend получает `task_id`.
5. Результат принимается через webhook или polling `/status/{task_id}`.
6. Результат отображается в UI платформы клиента.

## 7. Требования к webhook

- допускается только `https` (production);
- host должен входить в `WEBHOOK_ALLOWED_HOSTS`;
- endpoint должен быть доступен извне.

При нарушении условий API вернет `422` по полю `webhook_url`.

## 8. Типовые ошибки

### 401 / 403

- отсутствует или неверен `X-API-Key`;
- недействительный/просроченный JWT.

### 400

Переданы одновременно `X-API-Key` и `Bearer` токен.

### 404 (`Unknown task_id`)

- неверный `task_id`;
- отсутствует доступ к задаче в текущем auth-контексте.

### 422

- ошибка структуры запроса;
- некорректный UUID;
- webhook host не разрешен.

### 429

Превышен лимит запросов (рекомендуется backoff/retry).

## 9. Рекомендации для production

- хранить API ключ только server-side;
- реализовать retry и timeout policy;
- использовать idempotency на стороне клиента;
- логировать запросы с привязкой к `task_id`;
- обеспечить fallback на polling при недоступности webhook.

## 10. Контрольный чеклист перед запуском

- [ ] backend клиента вызывает API по HTTPS;
- [ ] API ключ хранится только на сервере;
- [ ] webhook endpoint настроен и доступен;
- [ ] реализован polling `/status/{task_id}`;
- [ ] реализована обработка 4xx/5xx;
- [ ] включено логирование по `task_id`.

## 11. Паттерн «кнопка в UI»

Рекомендуемый подход:

1. UI -> backend клиента (`POST /your/api/analyze`);
2. backend клиента -> наш API (`POST /api/v1/analyze`);
3. backend клиента сохраняет `task_id`;
4. UI получает результат через backend клиента.

Это позволяет не раскрывать `X-API-Key` в браузере и централизовать интеграционную логику.

