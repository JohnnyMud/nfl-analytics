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
- [`AGENTS.md`](AGENTS.md) — invariants and conventions for coding agents
- [`docs/agent-briefs/`](docs/agent-briefs/README.md) — paste-ready task briefs

## Current status

Implementation starting. The active task is
[Week 1 minimum viable capture](docs/specs/week1-minimum-capture.md) — a deliberately
descoped version of the odds pipeline that must be running before the 2026 Week 1 opener
(NE @ SEA, Sept 9). Odds history is the only data in this project that cannot be backfilled
after the fact, which is why it is first
(see [ADR-0001](docs/adr/0001-capture-odds-before-everything-else.md)).
