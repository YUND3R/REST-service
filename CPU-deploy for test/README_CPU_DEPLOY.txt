CPU test deployment
===================

This folder is for deploying the service on a normal CPU/VPS server without real model inference.
It starts the API, nginx, Redis, PostgreSQL, webhook dispatcher and CPU mock workers.

The mock workers do not load torch, transformers or GPU models. They only verify that:
- API Gateway accepts requests;
- Redis Streams queues work;
- workers consume tasks;
- status/result data is saved in Redis;
- history is saved in PostgreSQL;
- webhook events are placed into queue:webhook.

Run on server:

1. Install Docker:
   sudo apt update
   sudo apt install -y docker.io docker-compose-plugin git
   sudo systemctl enable --now docker

2. Clone project:
   git clone https://github.com/YUND3R/REST-service.git
   cd REST/CPU-deploy\ for\ test

3. Create env file:
   cp env.sample .env
   nano .env

4. Start:
   docker compose --env-file .env up -d --build

5. Check:
   docker compose ps
   curl http://localhost:8080/health

Default local API key from the migration:
   dev-api-key

Example request:

curl -X POST http://localhost:8080/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key" \
  -d '{
    "student_id": "student-1",
    "task_description": "Return x + 1",
    "code": "def add_one(x): return x - 1",
    "webhook_url": "https://example.com/webhook"
  }'

Then copy task_id from the response and check:

curl -H "X-API-Key: dev-api-key" http://localhost:8080/api/v1/status/TASK_ID_HERE

Stop:
   docker compose down

Remove test database/Redis data:
   docker compose down -v

Important:
- This deployment is only for testing REST-service behavior on CPU.
- It does not test real quality or latency of ML models.
- For real inference use the main GPU deployment.
