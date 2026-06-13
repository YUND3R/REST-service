# Руководство для клиента: интеграция с API

Этот документ для внешней команды, которая хочет подключиться к API как к сервису.

Без DevOps-деталей, только практические шаги интеграции.

---

## 1) Что вы получаете

API по HTTPS для:

- анализа кода;
- генерации задач;
- полного пайплайна (анализ + генерация);
- получения статуса асинхронной задачи;
- доступа к истории/профилю студента.

Базовый URL:

`https://test4rest-service.ru/api/v1`

---

## 2) Что нужно от вашей команды

Минимально:

1. Backend, который умеет делать HTTPS-запросы.
2. Ваш `X-API-Key` (выдается нашей стороной).
3. HTTPS webhook endpoint (куда API пришлёт результат).
4. Логика poll/retry для `status`.

Важно: `X-API-Key` хранится только на backend, не в frontend.

---

## 3) Модель авторизации

Есть 2 режима:

1. **Сервисный** — `X-API-Key`
2. **Пользовательский** — `Bearer JWT`

Используйте **либо** API key, **либо** JWT в одном запросе.

### Как получить JWT пользователя

1. `POST /auth/register` (с `X-API-Key`) -> получите `user_id` и `access_token`
2. `POST /auth/token` (с `X-API-Key`) -> перевыпуск `access_token` по `user_id`

---

## 4) Быстрый старт (за 15 минут)

### Шаг 1. Проверка доступности

```bash
curl -s "https://test4rest-service.ru/health/ready"
```

Ожидается `status=ready`.

### Шаг 2. Регистрация пользователя платформой

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

Сохраните `user_id` у себя в БД.

### Шаг 3. Запуск анализа

```bash
curl -X POST "https://test4rest-service.ru/api/v1/analyze" \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "PUT_USER_ID_HERE",
    "task_description": "Найди проблемы в коде",
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

### Шаг 4. Проверка статуса

```bash
curl "https://test4rest-service.ru/api/v1/status/<TASK_ID>" \
  -H "X-API-Key: <YOUR_API_KEY>"
```

Статусы:
- `pending`
- `processing`
- `done`
- `failed`

---

## 5) Основные endpoints

### Auth

- `POST /auth/register`
- `POST /auth/token`

### Задачи

- `POST /analyze`
- `POST /generate`
- `POST /pipeline`
- `GET /status/{task_id}`

### Данные студента

- `GET /students/{student_id}/history`
- `GET /students/{student_id}/profile`

---

## 6) Рекомендованный integration flow

1. Пользователь регистрируется/логинится у вас.
2. Ваш backend получает/хранит `user_id` и JWT через `/auth/*`.
3. Пользователь нажимает “Проверить код”.
4. Ваш backend отправляет `POST /analyze`.
5. Получает `task_id`.
6. Ждёт webhook или делает polling `GET /status/{task_id}`.
7. Показывает результат в UI.

---

## 7) Требования к webhook

- Только `https` (в production).
- Host должен входить в whitelist `WEBHOOK_ALLOWED_HOSTS`.
- Публично доступный endpoint.

Если host не разрешён, API вернёт `422` с ошибкой по `webhook_url`.

---

## 8) Ошибки, которые встретите чаще всего

### `401/403` авторизация

- неверный или отсутствующий `X-API-Key`;
- недействительный/просроченный JWT.

### `400` одновременно API key и JWT

Переданы оба заголовка авторизации в одном запросе.

### `404 Unknown task_id`

- неправильный `task_id`;
- нет доступа к задаче в контексте текущей авторизации.

### `422` валидация body

- неверный формат поля;
- webhook host не разрешён;
- неверный UUID и т.д.

### `429 Rate limit exceeded`

Слишком много запросов за период — используйте backoff/retry.

---

## 9) Практические рекомендации

- Храните `user_id` и связь с вашим internal user.
- Не храните API key в браузере.
- Делайте idempotency на вашей стороне для повторных отправок.
- Добавьте retry (например 3 попытки с backoff) на 5xx/timeout.
- Для UX показывайте прогресс: `pending` -> `processing` -> `done`.

---

## 10) Мини-чеклист перед production

- Ваш backend вызывает API только по HTTPS
- API key хранится только server-side
- Настроен рабочий webhook endpoint
- Реализован polling `/status/{task_id}`
- Есть обработка 4xx/5xx и retry
- Логи запросов и correlation по `task_id`

---

## 11) Пример “кнопка в UI”

UI-кнопка -> ваш backend -> наш API:

1. UI: `POST /your/api/analyze`
2. Ваш backend: `POST /api/v1/analyze`
3. Ваш backend сохраняет `task_id`
4. UI опрашивает ваш backend по статусу

Так клиенту не нужно знать API key и внутреннюю авторизацию.

