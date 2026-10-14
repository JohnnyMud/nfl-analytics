# NFL Analytics & Predictive Modeling Platform

A centralized NFL statistics database, interactive analytics interface, and research
environment for testing NFL hypotheses and evaluating predictive models.

## Why

Existing NFL stat sites make simple questions expensive: many pages, ads, and
disconnected statistical views. This platform is a fast, data-dense alternative built
around exploration, matchup analysis, and honest evaluation of predictive claims.

The differentiator is not "here is who will win." It is:

> "What actually matters when predicting this game or player?" — and the ability to
> explore the data, inspect the model, see the features that drive it, and check
> whether the edge existed historically.

## Core goals

1. Centralized, high-quality NFL player / team / game / historical data.
2. Polished, low-friction UI for exploring stats and comparing players, teams, matchups.
3. Reliable ingestion pipeline that updates continuously through the season.
4. Predictive models for game outcomes and player performance.
5. Rigorous investigation of which features actually carry predictive information.
6. Comparison of model probabilities vs. market-implied probabilities.
7. Systematic backtesting — calibration and out-of-sample performance, not headline accuracy.
8. Production-quality engineering throughout.

## Product surfaces

| Surface | Contents |
| --- | --- |
| **Player page** | Season + career stats, game logs, rolling averages, home/away and opponent splits, usage trends (snap %, target share), advanced metrics, upcoming matchup, projection + model prediction |
| **Team page** | Record, offensive/defensive stats, advanced team metrics (EPA/play, success rate), recent form, splits, strength of schedule, upcoming games, trends |
| **Game page** | Records, recent form, off/def efficiency, key player matchups, injuries, weather, historical series, betting lines, predicted score + win prob, player projections |
| **Research** | Feature-importance explorer, hypothesis tests, calibration plots, backtest results by market and confidence bucket |

## Modeling targets

**Game level:** win probability, point differential, predicted score, spread cover
probability, over/under probability.

**Player level:** passing yards / TDs / INTs, rushing yards / attempts, receiving yards /
receptions / targets, touchdowns — eventually priced against player prop lines.

## Non-negotiable principles

- **No leakage.** A model may only use information available before kickoff. Every
  feature carries an explicit as-of timestamp.
- **Time-aware validation.** Walk-forward / expanding-window splits by season and week.
  Never random k-fold over historical games.
- **Accuracy ≠ profitability.** Report both, separately. A well-calibrated model can be
  accurate and still have zero edge if the market already prices the same information.
- **Reproducibility over cherry-picking.** Backtests are systematic and versioned; no
  selective highlighting of winning predictions.
- **Clarity over clutter.** Fewer, well-built features beat a large pile of shallow ones.

## Repo layout (planned)

```
ingest/        source adapters (nflverse, odds, weather) — raw → bronze
transform/     dbt-style or SQL models — bronze → silver → feature marts
features/      point-in-time feature builders + registry
models/        training, tuning, registry, prediction jobs
backtest/      walk-forward harness, calibration, ROI/CLV analysis
api/           FastAPI service (read layer over marts)
web/           React + TypeScript frontend
infra/         Docker, migrations, CI/CD, scheduling
docs/          architecture, data sources, ADRs, research writeups
```

## Docs

- [`docs/data-sources.md`](docs/data-sources.md) — evaluated data sources, cadence, licensing
- [`docs/architecture.md`](docs/architecture.md) — system design, stack decisions, staged roadmap
- [`docs/adr/`](docs/adr/README.md) — architecture decision records
- [`docs/specs/odds-snapshot-pipeline.md`](docs/specs/odds-snapshot-pipeline.md) — full pipeline design
- [`docs/specs/week1-minimum-capture.md`](docs/specs/week1-minimum-capture.md) — **active odds task**
- [`docs/specs/rush-yards-phase1.md`](docs/specs/rush-yards-phase1.md) — **active modeling task** (RB rush yards)
- [`backtest/rush_yards_walkthrough.ipynb`](backtest/rush_yards_walkthrough.ipynb) — fit + predict walkthrough (in-memory slate), then a viewer over stored runs
- [`backtest/rush_yards_lab.ipynb`](backtest/rush_yards_lab.ipynb) — feature lab: performance, feature importance, ablations, add/drop experiments (read-only)
- [`AGENTS.md`](AGENTS.md) — invariants and conventions for coding agents
- [`docs/agent-briefs/`](docs/agent-briefs/README.md) — paste-ready task briefs

## Current status

- **Odds capture.** [Week 1 minimum viable capture](docs/specs/week1-minimum-capture.md)
  came first because odds history is the only data here that cannot be backfilled
  (see [ADR-0001](docs/adr/0001-capture-odds-before-everything-else.md)).
- **Stats warehouse.** nflverse teams, players, schedules, box scores, injuries, and
  depth-chart snapshots for 2016–2026 in Supabase Postgres, refreshed by GitHub Actions.
- **First model: RB rushing yards.** A walk-forward backtest over 2017–2025 (weekly
  refits, train from 2016) stores every prediction and MAE/RMSE row in `model.*`. The
  headline `pregame_safe` models beat both mandatory baselines on RMSE by about 0.9
  yards; on MAE only LightGBM edges the season-to-date baseline, by 0.02 yards.
  Results and run ids are in [the spec](docs/specs/rush-yards-phase1.md#11-results).
  Upcoming-week predictions are stored unlabeled and shown on the player page's
  Predictions tab.

```bash
make rush-walk-forward                    # backtest both feature subsets, write model.*
make rush-predict-upcoming SEASON=2026 WEEK=7
make rush-report RUN_IDS="<run_id> ..."   # read stored rows; no args lists runs
```
