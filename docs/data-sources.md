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

### OpticOdds (workspace integration — prototype only)
A sports-betting data API with odds, fixtures, markets, player props, futures,
SGP pricing, results/grading, and injuries. Connected in this workspace, which is how
the spec's endpoint limits and market-discovery design were validated against real
responses.

**Not a production data path.** It is an interactive assistant tool, not a callable API
from a deployed scheduler, and OpticOdds itself is enterprise-only — no self-serve signup,
no public pricing, access via a sales form, pricing reportedly starting around $5,000/month
per sport ([OpticOdds](https://opticodds.com/api-integration)). It stays useful for
research and contract validation but is not the production adapter.

### The Odds API (production primary, free tier)
[the-odds-api.com](https://the-odds-api.com/sports-odds-data/nfl-odds.html) — the production
odds source for now. Self-serve, open free tier (500 credits/month, no card), covers NFL game
lines (moneyline, spreads, totals) and player props, and returns the full slate across books
and markets in a single request. Base URL `https://api.the-odds-api.com/v4`; auth via
`apiKey` query parameter; sport key `americanfootball_nfl`.

Why it fits this project right now:
- **Open and self-serve.** Unlike odds-api.io (which has paused new free keys indefinitely),
  The Odds API's free tier is available and covers NFL game lines on free.
- **Full-slate-in-one-call.** A 16-game snapshot is one request, not 16 — efficient and a good
  fit for a coarse capture cadence.
- Covers game lines **and** player props, so the same adapter serves both the Week 1 capture
  and the later player-props scope.
- Transparent, low pricing suits a portfolio project; Pro ($29/mo) is the documented
  upgrade for the full cadence and sharp books.

Tradeoffs accepted on free:
- **Volume is the constraint, not access.** Credits are not requests (a call costs
  markets × regions credits), so 500 credits ≈ 166 full-slate calls/month. A coarse weekly
  cadence fits; the full research-grade tiered cadence (2-minute closing snapshots) does not.
  The adapter tracks credit spend and surfaces `RateBudgetExceeded` so the orchestrator
  coarsens rather than failing silently.
- **No sharp books on free.** Pinnacle (eu region) is paid, so no no-vig / sharp-reference
  baselining is possible on free. Deferred to the Pro upgrade.

### The Odds API Pro (upgrade path, $29/mo)
The documented upgrade when sharp-reference analysis and the full tiered cadence become
necessary. Unlocks the full tiered cadence at scale, adds Pinnacle (eu region) for no-vig
baselining, and covers ~50 books. Reached by writing a second adapter behind the same
`OddsProvider` port — the pipeline, schema, and tests are unchanged.

### Evaluated alternatives (not selected)

| Provider | Free tier | NFL | Props | Pricing | Why not primary |
| --- | --- | --- | --- | --- | --- |
| [odds-api.io](https://odds-api.io/sports/nfl) | was 100 req/hr | yes | yes | paid tiers | **Free keys paused indefinitely** — not a reliable path |
| [SharpAPI](https://sharpapi.io/odds/nfl) | 12 req/min | yes | yes | $79–399/mo | Built-in +EV/no-vig is nice but only 2 books on free, 60s delay |
| [SportsGameOdds](https://sportsgameodds.com/leagues/nfl-odds-api) | 2,500 obj/mo | yes | yes | $99–499/mo | Settlement included; pricier, less SDK ecosystem |
| OpticOdds | none (sales) | yes | yes | ~$5,000/mo | Enterprise-only; see above |

The `OddsProvider` port means any of these can be added as a second adapter later without
rearchitecting — useful if a specific research need (e.g. SGP pricing, broader book
coverage) justifies it.

### nflverse historical closing lines (free, no API)
nflverse ships historical scoring lines, win totals, and opening/closing spreads as part of
its release data. These cover the entire CLV and market-comparison backtesting scope at
zero cost with no odds API at all. The live odds API is only needed for capturing this
season's line movement in real time — all historical research uses nflverse directly.

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
