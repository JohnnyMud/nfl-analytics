# Brief 02 — OddsProvider port and vendor adapter

Paste the block below into a fresh agent session. Requires brief 01 to be merged.

---

Read `AGENTS.md`, `.cursor/rules/10-odds-capture.mdc`,
`docs/adr/0004-odds-access-path.md`, and `docs/specs/odds-snapshot-pipeline.md` §2 and §4.

**Task:** implement the vendor abstraction and one concrete adapter. No database writes in
this brief — the adapter returns normalized objects and nothing else.

**Deliverables**

1. `ingest/odds/port.py` — a `Protocol` named `OddsProvider` with:
   - `list_fixtures(league, season_year, *, start_after, start_before) -> list[Fixture]`
   - `list_markets(vendor_fixture_id, sportsbooks) -> list[MarketRef]`
   - `get_odds(vendor_fixture_ids, sportsbooks, markets) -> list[Quote]`
   - `get_results(vendor_fixture_ids) -> list[FixtureResult]`
2. `ingest/odds/types.py` — Pydantic v2 models for `Fixture`, `MarketRef`, `Quote`,
   `FixtureResult`. Every model carries `raw: dict` holding the untouched vendor payload,
   and `vendor: str`. No vendor-specific field names in these types.
3. `ingest/odds/opticodds.py` — the adapter. It owns:
   - request batching: **max 5 combined** fixture/player/team IDs, **max 5 sportsbooks**
     per odds request. Batching is the adapter's job, not the caller's.
   - a client-side token bucket rate limiter, ceiling from config
   - retry with jittered exponential backoff on **5xx and 429 only**; a 4xx raises
     `VendorContractError` immediately and is never retried
   - normalization into the types above, preserving `raw`
4. `tests/fixtures/vendor/` — recorded JSON responses. Capture real ones, and include at
   minimum: a regular-season fixtures response, a markets response for a regular-season
   fixture, an odds response with main game markets, and one error response (400).
5. Contract tests running fully offline against those fixtures.

**Behaviors that must be tested**

- Batching: 16 fixtures × 7 sportsbooks produces the expected number of requests with correct
  ID grouping, and no batch exceeds either limit.
- A 400 raises `VendorContractError` and does **not** retry.
- A 500 retries with backoff, then succeeds on a later attempt.
- Normalization preserves `raw` byte-for-byte equivalent content.
- `list_markets` returns an empty list without raising when a book offers no markets for a
  fixture — this is a normal state, not an error.

**Watch out for**

- Market availability differs by fixture, by book, and by point in the season. Preseason
  fixtures expose game-level markets only, with no player props. Do not hardcode a market
  list, and do not treat an empty market list as a failure.
- The vendor's week label is not always the NFL week: regular-season fixtures carry a normal
  `1`–`18`, but preseason fixtures carry a calendar-style week number. Store the vendor's
  label verbatim as a string in `vendor_season_week`. Do not parse it into `nfl_week` here.
- Some fixtures are at neutral or international venues. `venue_neutral` is real and matters
  later for travel and weather features. Carry it through.
- `sport` and `league` alone are not valid odds selectors. Resolve fixtures first.

**Before writing code,** restate the task, list files, and state which core invariant this
change could plausibly violate. Do not start until I confirm.

**Done when:** contract tests pass offline, no live network call exists in the test suite,
`mypy` is clean, and no vendor-specific type escapes `ingest/odds/opticodds.py`.
