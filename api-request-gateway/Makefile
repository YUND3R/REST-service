.PHONY: lint fmt compile test sync up down

sync:
	uv sync --all-groups

lint:
	uv run ruff check gateway workers models db tests

test:
	uv run pytest -q

compile:
	uv run python -m compileall -q gateway workers models db tests

up:
	docker compose up -d --build

down:
	docker compose down

fmt:
	uv run ruff format gateway workers models db tests
