# Prefer the local venv after `make setup`; CI uses the runner's Python.
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

# App commands (migrate, capture, api) use SUPABASE_URL from `.env`.
# A process-level DATABASE_URL overrides that (GitHub Actions secrets, and
# tests). Tests always pin local Postgres so they cannot create or drop
# databases on Supabase.
TEST_DATABASE_URL := postgresql+psycopg://postgres:postgres@localhost:5432/nfl_analytics

.PHONY: setup db-up migrate test lint capture-dry api web nflverse-games nflverse-injuries nflverse-players nflverse-player-stats nflverse-depth-charts nflverse-backfill rush-walk-forward rush-predict-upcoming rush-report rush-prune-runs

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

nflverse-players:
	$(PYTHON) -m ingest.nflverse.players

nflverse-player-stats:
	$(PYTHON) -m ingest.nflverse.player_stats

nflverse-depth-charts:
	$(PYTHON) -m ingest.nflverse.depth_charts

# Historical facts for rush_rb_v1. Players first so later FKs succeed.
# Nightly current-season jobs stay on the targets above (no season env).
# Supabase already holds 2016-2026; rerunning this rewrites rows in place.
# Depth charts are not in this rewrite. Week-only seasons derive snapshot_at
# from the schedule; a different instant would insert a second key. Run
# `nflverse-depth-charts` (current season, or NFLVERSE_SEASON_START/END).
nflverse-backfill:
	NFLVERSE_SEASON_START=2016 NFLVERSE_SEASON_END=2025 $(PYTHON) -m ingest.nflverse.players
	NFLVERSE_SEASON_START=2016 NFLVERSE_SEASON_END=2025 $(PYTHON) -m ingest.nflverse.schedules
	NFLVERSE_SEASON_START=2016 NFLVERSE_SEASON_END=2025 $(PYTHON) -m ingest.nflverse.player_stats
	NFLVERSE_SEASON_START=2016 NFLVERSE_SEASON_END=2025 $(PYTHON) -m ingest.nflverse.injuries

# Walk-forward backtest against DATABASE_URL. Writes model.* rows unless --dry-run.
rush-walk-forward:
	$(PYTHON) -m models.rush_yards backtest --subset pregame_safe
	$(PYTHON) -m models.rush_yards backtest --subset full

rush-predict-upcoming:
	$(PYTHON) -m models.rush_yards predict-upcoming --season $(SEASON) --week $(WEEK)

rush-report:
	$(PYTHON) -m backtest.rush_yards_report $(RUN_IDS)

# Deletes model.* rows for all but the newest KEEP runs. Run by hand only.
rush-prune-runs:
	$(PYTHON) -m models.rush_yards prune --keep $(KEEP)
