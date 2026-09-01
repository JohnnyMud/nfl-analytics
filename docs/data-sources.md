# Data Sources

Evaluation criteria: reliability, legality/licensing, cost, update frequency, historical
depth, and whether ingestion is reproducible (documented API/files) rather than manual.

## Tier 1 — foundation (free, licensed, reproducible)

### nflverse
The canonical open NFL data project. Publishes tidy **parquet** files to GitHub releases,
built by automated GitHub Actions.

- Play-by-play from **1999–present**, with precomputed EPA, win probability, air yards,
  CPOE, success rate (<https://github.com/nflverse/nflfastR>)
- Player stats, team stats, rosters, depth charts, **snap counts**, **injuries**,
  schedules, **historical scoring lines / win totals**, officials, draft, combine,
  contracts, trades, Next Gen Stats, ESPN QBR, participation (personnel + pass rushers),
  FTN charting subset (<https://nflreadr.nflverse.com/reference/index.html>)
- Cross-source ID mappings (gsis / pfr / espn / sleeper) — critical for joining
- Cadence: **nightly after each game day**, plus intra-gameday updates; raw pbp JSON
  usually available **within ~15 min of a game ending**. Re-pull Wed→Thu overnight to
  capture NFL stat corrections (<https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html>)
- Data dictionaries published per dataset — use them to drive schema generation

**Python access:** prefer **`nflreadpy`**, the maintained Python port of `nflreadr`
(<https://github.com/nflverse>). The older `nfl_data_py` has historically lagged on
current-season releases (<https://github.com/nflverse/nfl_data_py/issues>). Best practice
either way: read the release parquet URLs directly so the pipeline never depends on a
wrapper's release cadence.

> Decision: read nflverse-data release parquet over HTTPS directly into our own bronze
> layer. Wrappers are convenience, not infrastructure.

### OpticOdds (connected)
Sports-betting data API v3 — odds, fixtures, markets, **player props**, futures,
same-game-parlay pricing, results/grading, and injuries. Already available as a connector
in this workspace, which covers the hardest part of the betting side: multi-book pricing
and line movement.

Use for: opening/closing lines, per-book prop lines, line movement snapshots, CLV
(closing line value) measurement, and grading historical bets.

Critical requirement: **snapshot odds on a schedule and store every observation
immutably**. Odds APIs are point-in-time; without our own time series we can never
reconstruct what the market looked like before a prediction, and CLV/backtests become
impossible. This is the single most time-sensitive piece of the build — historical odds
cannot be recovered later.

### Weather
Two-part problem: forecast at prediction time and actual at kickoff. Keep both — the
model must use the forecast that existed pre-kickoff, while research can use actuals.
Roof/surface come from nflverse schedules; only outdoor stadiums need weather.
Candidates: Open-Meteo (free, historical + forecast archive), NWS API. Stadium
lat/long is a small static reference table we maintain.

## Tier 2 — evaluate later

- **Pro Football Reference** — deep historical splits, but terms of use restrict
  automated collection; prefer nflverse's licensed PFR-derived tables instead.
- **NFL Next Gen Stats** — partially exposed through nflverse; direct endpoints are
  undocumented and unstable.
- **PFF / SIS / FTN (paid)** — grades and charting depth. Only justified if a specific
  hypothesis needs charting data nflverse doesn't carry.
- **Big Data Bowl tracking data** — player tracking for select seasons, Kaggle-licensed
  (<https://www.kaggle.com/c/nfl-big-data-bowl-2025/data>). Excellent for research, not
  for a live pipeline.

## Ingestion rules

1. **Bronze is immutable.** Land raw payloads unmodified with `ingested_at` +
   source URL/etag. Never overwrite; re-derive downstream.
2. **Everything is bitemporal** where it changes: injuries, depth charts, odds, weather
   forecasts, and stat corrections all need `valid_from` / `observed_at`. Late-arriving
   stat corrections are a real leakage vector.
3. **Idempotent, resumable loads** keyed on natural keys (`game_id`, `play_id`,
   `player_id`, `book` + `market` + `observed_at`).
4. **Contract tests on every source.** Row counts, schema drift, null rates, and
   referential checks fail the run loudly rather than silently poisoning features.
5. **ID resolution is its own layer.** One canonical player/team dimension; all sources
   map into it via nflverse ID crosswalks plus a manual override table.
