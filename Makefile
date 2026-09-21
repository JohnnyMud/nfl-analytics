# Prefer the local venv after `make setup`; CI uses the runner's Python.
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

# App commands (migrate, capture, api) read DATABASE_URL from `.env` locally
# or from the process environment (GitHub Actions secrets in production).
# Tests always pin local Postgres so a production URL in `.env` cannot drop
# throwaway databases against Supabase.
TEST_DATABASE_URL := postgresql+psycopg://postgres:postgres@localhost:5432/nfl_analytics

.PHONY: setup db-up migrate test lint capture-dry api web nflverse-games nflverse-injuries nflverse-player-stats

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e ".[dev]"
	.venv/bin/python -m pip install pre-commit
	.venv/bin/pre-commit install

db-up:
	docker compose up -d --wait

migrate:
	$(PYTHON) -m alembic upgrade head

test:
	DATABASE_URL=$(TEST_DATABASE_URL) APP_ENV=ci $(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy --strict features models ingest

capture-dry:
	$(PYTHON) -m ingest.odds tick --dry-run

api:
	$(PYTHON) -m api

web:
	npm --prefix web run dev

nflverse-games:
	$(PYTHON) -m ingest.nflverse.schedules

nflverse-injuries:
	$(PYTHON) -m ingest.nflverse.injuries

nflverse-player-stats:
	$(PYTHON) -m ingest.nflverse.player_stats
