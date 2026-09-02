# Prefer the local venv after `make setup`; CI uses the runner's Python.
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

export DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5432/nfl_analytics

.PHONY: setup db-up migrate test lint capture-dry

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
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy --strict features models ingest

capture-dry:
	@echo "capture not implemented"
