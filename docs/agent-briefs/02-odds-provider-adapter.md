# Brief 02 — OddsProvider port and vendor adapter

Paste the block below into a fresh agent session. Requires brief 01 to be merged.

---

Read `AGENTS.md`, `.cursor/rules/10-odds-capture.mdc`,
`docs/adr/0004-odds-access-path.md`, and `docs/specs/odds-snapshot-pipeline.md` §2 and §4.

**Task:** implement the vendor abstraction and one concrete adapter. No database writes in
this brief — the adapter returns normalized objects and nothing else.

**Vendor selection (decided in ADR-0004).** The concrete adapter is for **The Odds API**
(the-odds-api.com), the production primary. It is self-serve, has an open free tier
(500 credits/month, no card), covers NFL game lines (moneyline, spreads, totals) and player
props, and returns the full NFL slate across books and markets in a single request. The
workspace OpticOdds integration is **not** the adapter target — it is enterprise-only
(~$5,000/mo, sales-gated) and is an interactive tool, not a callable API from a deployed
scheduler. The Odds API key is read from the `ODDS_API_KEY` environment variable.

**Free-tier volume constraint (important).** Credits are not requests: a call costs
`markets × regions` credits. A 3-market (h2h, spreads, totals) × 1-region (us) call costs 3
credits, so 500 credits ≈ 166 full-slate calls/month. Because one call returns the entire
slate, that is enough for a **coarse** weekly cadence, but the full research-grade tiered
cadence (2-minute closing snapshots) does not fit on free. The adapter must track credit spend
and surface a `RateBudgetExceeded` signal so the orchestrator coarsens the cadence rather
than failing silently. The full tiered cadence + sharp-reference books come with Pro
($29/mo) — reached by writing a second adapter behind the same port, not by changing the
pipeline.

**Deliverables**

1. `ingest/odds/port.py` — a `Protocol` named `OddsProvider` with:
   - `list_fixtures(league, season_year, *, start_after, start_before) -> list[Fixture]`
   - `list_markets(vendor_fixture_id, sportsbooks) -> list[MarketRef]`
   - `get_odds(vendor_fixture_ids, sportsbooks, markets) -> list[Quote]`
   - `get_results(vendor_fixture_ids) -> list[FixtureResult]`
2. `ingest/odds/types.py` — Pydantic v2 models for `Fixture`, `MarketRef`, `Quote`,
   `FixtureResult`. Every model carries `raw: dict` holding the untouched vendor payload,
   and `vendor: str`. No vendor-specific field names in these types.
3. `ingest/odds/the_odds_api.py` — the adapter for The Odds API (v4). It owns:
   - mapping our `league`/`sport` identifiers to The Odds API's sport keys
     (`americanfootball_nfl`, `americanfootball_nfl_preseason`).
   - the full-slate fetch: `GET /v4/sports/{sport}/odds?regions=us&markets=h2h,spreads,totals&oddsFormat=american&apiKey=KEY`
     returns all games, all books, all markets in one response. Keep `get_odds` accepting a
     list of fixture IDs for interface symmetry, but document that granularity is per-sport.
   - region selection (`us` for soft US books; `eu` is Pinnacle but paid — absent on free).
   - a client-side rate limiter sized to the plan ceiling, plus a **credit spend tracker**
     that raises `RateBudgetExceeded` before the monthly budget is exhausted.
   - retry with jittered exponential backoff on **5xx and 429 only**; a 4xx raises
     `VendorContractError` immediately and is never retried.
   - normalization into the types above, preserving `raw`.
4. `tests/fixtures/vendor/` — recorded JSON responses captured from real The Odds API
   calls. Include at minimum: an NFL fixtures/odds response with main game markets, an odds
   response with player props, and one 400 error response.
5. Contract tests running fully offline against those fixtures.

**The Odds API specifics to get right**

- **Full-slate-in-one-call.** One `GET /v4/sports/{sport}/odds` returns every game across
  all books and markets. This is the key efficiency — a 16-game slate snapshot is 1 call,
  not 16.
- **Credit accounting is mandatory.** Each call costs `markets × regions` credits (historical
  odds cost 10×). The adapter must compute the credit cost of a request before sending it,
  track running monthly spend, and raise `RateBudgetExceeded` rather than letting the call
  fail with a quota error. This is what lets the orchestrator coarsen the cadence on free.
- **Book set.** Default to US books (`region=us`); the sportsbook set is config, not
  hardcoded. Pinnacle (eu region) is the sharp reference for no-vig baselining but is paid —
  absent on free, so no no-vig work is possible on free.
- **Market availability varies.** Preseason may expose only game-level markets; player props
  appear as the regular season approaches. Do not hardcode a market list; treat an empty
  market list as a normal state, not an error.
- **Vendor week vs NFL week.** The Odds API returns a `season` (e.g. `2026`) and the sport
  key distinguishes preseason from regular season, but does not provide a clean NFL week
  number. Store the vendor's season and sport key verbatim; `nfl_week` is resolved later in a
  separate mapping layer and is nullable by design.
- **Neutral and international venues.** Carry `home_team`/`away_team` and any neutral-site
  flag through. International-series fixtures are at neutral venues.
- **Odds format.** The Odds API supports American and decimal via `oddsFormat`; default to
  American, store both if available.

**Behaviors that must be tested**

- Credit cost is computed correctly for a multi-market, multi-region request.
- Running monthly credit spend is tracked and `RateBudgetExceeded` is raised before the
  budget is exhausted.
- Normalization preserves `raw` byte-for-byte equivalent content.
- A 400 raises `VendorContractError` and does **not** retry.
- A 500 retries with backoff, then succeeds on a later attempt.
- `list_markets` returns an empty list without raising when a book offers no markets for a
  fixture.
- Neutral-venue flag is preserved through normalization.

**Watch out for**

- `commence_time` is UTC ISO 8601 — parse and store as timezone-aware.
- The free tier is low volume; the adapter must not require Pro-only endpoints to function
  for game lines. Player props may require Pro — guard prop fetching behind a capability flag
  rather than failing hard when the plan does not include them.
- The full research-grade tiered cadence (2-minute closing snapshots) will not fit on free.
  Document this so the orchestrator coarsens on free and enables the full cadence only on Pro.

**Before writing code,** restate the task, list files, and state which core invariant this
change could plausibly violate. Do not start until I confirm.

**Done when:** contract tests pass offline, no live network call exists in the test suite,
`mypy` is clean, and no vendor-specific type escapes `ingest/odds/the_odds_api.py`.
