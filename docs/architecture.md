# Architecture & Roadmap

## Guiding constraint

Technology choices follow the problem. The dataset here is small by industry standards
(~1M plays per decade, a few hundred games per season, low-thousands of odds snapshots
per week). Nothing about the volume requires exotic infrastructure. What the project
*does* require is **temporal correctness**, **reproducibility**, and **clean layer
separation**. Those are the axes worth engineering hard on.

## Layers

```
sources ──► ingest ──► bronze (raw, immutable, timestamped)
                          │
                          ▼
                       silver (typed, deduped, conformed dims: player/team/game)
                          │
                          ▼
                  feature marts (point-in-time, as-of joined)
                     │              │
                     ▼              ▼
                 training       serving (API reads only from here)
                     │
                     ▼
              model registry ──► predictions table ──► backtest harness
```

Hard rule: the API never computes features and never calls a model inline. It reads
precomputed rows. Prediction is a batch job; serving is a lookup. This keeps p95 latency
trivial and makes every displayed number reproducible from a stored artifact.

## Stack

| Layer | Choice | Rationale |
| --- | --- | --- |
| Storage | **PostgreSQL** | Your strength; handles this scale easily. Partition pbp by season, odds snapshots by week. |
| Analytics scratch | **DuckDB** | Query nflverse parquet directly, no load step, for research and backfills. Pairs naturally with Postgres. |
| Transforms | **SQL, version-controlled** (dbt or plain SQL + migrations) | Transform logic must be reviewable and testable, not buried in Pandas. |
| Ingest / jobs | **Python + Prefect or Dagster** | Retries, scheduling, observability, backfills. Cron-only becomes unmaintainable once sources have different cadences. |
| API | **FastAPI + Pydantic v2 + SQLAlchemy 2.0** | Typed contracts, OpenAPI for free, frontend types generated from the schema. |
| Cache | **Redis** | Cache expensive aggregate endpoints; invalidate on pipeline completion, not TTL guessing. |
| Frontend | **React + TypeScript + Vite**, TanStack Query + Table, Recharts or visx | Data-dense tables and charts are the product. Types generated from OpenAPI. |
| Models | **LightGBM / XGBoost** baseline, statsmodels for inference | Tabular problem with strong feature interactions. Gradient boosting is the right default; PyTorch is not justified until sequence/tracking data enters. |
| Experiments | **MLflow** | Model registry, params, metrics, artifacts. Every displayed prediction traces to a run ID. |
| Infra | **Docker Compose** locally, one cloud host + managed Postgres | Deploy simply; complexity spent on data correctness instead. |
| CI | **GitHub Actions** | ruff + mypy (strict on `features/` and `models/`) + pytest, plus a nightly data-contract run. |

### What was actually built (drift from the table above)

The table is the original plan. As of the 2026 season:

- **Adopted:** Postgres (hosted on Supabase), FastAPI + Pydantic v2 + SQLAlchemy 2.0 +
  Alembic, React + TypeScript + Vite, native XGBoost and LightGBM, GitHub Actions for CI
  and the nightly nflverse jobs.
- **Not adopted:** DuckDB, dbt, Prefect/Dagster (jobs are GitHub Actions cron calling
  `python -m ingest.*`), Redis, MLflow (provenance is `run_id`, `model_version`, and
  `feature_set_version` on `model.prediction`), TanStack Query/Table, statsmodels,
  Docker Compose as the warehouse (the compose Postgres is a local development and test
  database; the data lives in Supabase).
- **Vendor:** odds come from The Odds API (`ingest/odds/the_odds_api.py`), not OpticOdds.
- **Order:** the first player target is RB rushing yards, not receiving yards.
- **Point-in-time caveat:** nflverse tables are upserted, not appended, so they are not
  point-in-time history. Injury reports have no publish time, and depth charts before
  2025 carry a derived instant. Models that use them are labelled `+full` and treated
  as an upper bound; headline numbers use `+pregame_safe`.

Rust or another systems language is **not** currently justified. Revisit only if
play-level tracking data or a heavy simulation loop (e.g. tens of thousands of game
simulations per slate) becomes a real bottleneck.

## Point-in-time discipline

This is where projects like this usually break, so it gets first-class treatment.

- Every feature is produced by a function with signature
  `f(entity_id, as_of_timestamp) -> value`, and the builder physically cannot read rows
  with `observed_at > as_of`.
- Feature rows are stored with the `as_of` they were computed for, so a backtest replays
  the exact vector the model would have seen.
- Rolling windows are computed over *prior games only*, with explicit handling of byes,
  short weeks, and missed games (do not silently forward-fill).
- Injury and depth-chart state uses the last report **before** kickoff, not the final
  post-game status.
- Odds features use a fixed snapshot policy (e.g. Sunday open, T-60min) declared per
  experiment; closing line is reserved for CLV evaluation, never as a feature.
- A dedicated **leakage test suite**: shuffle-time tests, future-row assertions, and a
  "does this feature beat the market suspiciously well?" tripwire.

## Evaluation contract

Every model ships with: log loss, Brier score, AUC where applicable, MAE/RMSE for
continuous targets, a reliability (calibration) curve, performance by confidence bucket,
and a walk-forward summary by season. Betting-oriented models add implied vs. model
probability, edge distribution, hit rate, ROI, max drawdown, performance vs. closing
line, and breakdown by market. Results are stored, not screenshotted.

Baselines are mandatory and must be beaten to claim anything: market-implied probability,
season-to-date average, and last-N average.

## Staged roadmap

**Stage 1 — Data foundation.** Postgres schema + migrations; nflverse backfill 1999→now
(pbp, player/team weekly, schedules, rosters, snap counts, injuries); canonical
player/team/game dimensions; data-contract tests; nightly refresh job. Deliverable: one
database that can answer any box-score or EPA question in SQL.

**Stage 2 — Odds capture (start early, in parallel).** Scheduled OpticOdds snapshots for
game lines and player props, stored immutably as a time series. Time-sensitive: this
history cannot be recreated later.

**Stage 3 — Read API + core pages.** FastAPI endpoints over silver marts; player, team,
and game pages with splits, game logs, rolling averages, and efficiency metrics. Ship
the stats product before the ML product.

**Stage 4 — Feature store + first models.** Point-in-time feature builders; game-outcome
model (win prob, margin) and one player target (receiving yards is a good first pick —
high volume, meaningful variance, clean usage features). Walk-forward validation against
the three mandatory baselines.

**Stage 5 — Backtest + research surfaces.** Calibration plots, feature importance /
permutation importance / SHAP, hypothesis tests, and the market-vs-model comparison view.
This is the stage that makes the project distinctive.

**Stage 6 — Breadth.** More prop markets, weather, opponent-adjusted metrics,
line-movement features, ensembles, and a public research writeup per hypothesis.
