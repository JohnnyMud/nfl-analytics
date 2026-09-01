# Spec: Odds Snapshot Pipeline

Status: Design complete, ready to implement
Owner: Johnny Mudawar
Related: ADR-0001, ADR-0002, ADR-0003, ADR-0004

## 1. Purpose

Continuously capture and permanently store the NFL betting market — game lines and player
props, per sportsbook, over time — so that later work can:

- reconstruct exactly what the market looked like at any instant before any kickoff
- measure model predictions against market-implied probability
- measure closing line value (CLV)
- study line movement as a feature and as a research subject

**Success criterion:** for any 2026 NFL game, we can produce the price of any captured
market at any requested pre-kickoff timestamp, or state definitively that we were not
observing at that time. No stale value is ever silently returned as if it were current.

**Non-goals:** live in-game odds, bet placement, arbitrage detection, non-NFL leagues
(schema stays league-agnostic, capture scope does not), and serving odds to a UI. This
component only captures and stores.

## 2. Architecture

```
                    ┌─────────────────────────────┐
   scheduler ──────►│  capture orchestrator       │
   (tier-aware)     │  - resolve fixtures         │
                    │  - compute due tiers        │
                    │  - build request batches    │
                    └──────────┬──────────────────┘
                               │ bounded worker pool
                               ▼
                    ┌─────────────────────────────┐
                    │  OddsProvider (port)        │
                    │   OpticOddsAdapter          │
                    │   FallbackAdapter           │
                    └──────────┬──────────────────┘
                               │ normalized quotes + raw payload
                               ▼
                    ┌─────────────────────────────┐
                    │  writer                     │
                    │  - open snapshot row        │
                    │  - diff vs market_state     │
                    │  - append changed rows      │
                    │  - close snapshot (outcome) │
                    └──────────┬──────────────────┘
                               ▼
             Postgres: odds_snapshot / odds_observation /
                       odds_market_state / odds_closing_line /
                       market_catalog / vendor_fixture
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │  validators + monitors      │
                    │  (gap, staleness, sanity,   │
                    │   cross-source agreement)   │
                    └─────────────────────────────┘
```

The orchestrator is stateless; all state lives in Postgres. Any run can be killed and
restarted without loss, because a snapshot is either closed with an outcome or visible as
`running`/abandoned and re-attempted.

## 3. Schema

Illustrative DDL — column names are the contract, types are negotiable.

```sql
-- Vendor fixture registry. Written on discovery, before our own game dimension exists.
CREATE TABLE vendor_fixture (
    vendor              text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    league              text        NOT NULL,
    season_year         int         NOT NULL,
    season_type         text        NOT NULL,   -- Preseason | Regular Season | Postseason
    vendor_season_week  text,                    -- vendor's own week label; NOT nfl week
    nfl_week            int,                     -- resolved later; nullable by design
    start_date          timestamptz NOT NULL,
    status              text        NOT NULL,
    home_team_vendor_id text        NOT NULL,
    away_team_vendor_id text        NOT NULL,
    home_abbr           text,
    away_abbr           text,
    venue_name          text,
    venue_location      text,
    venue_neutral       bool,
    game_id             text,                    -- FK to our dimension, resolved later
    raw                 jsonb       NOT NULL,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vendor, vendor_fixture_id)
);

-- One row per poll ATTEMPT. The record of coverage.
CREATE TABLE odds_snapshot (
    snapshot_id     bigserial   PRIMARY KEY,
    vendor          text        NOT NULL,
    tier            text        NOT NULL,   -- opening | slow | hourly | q15 | q5 | closing
    scope           jsonb       NOT NULL,   -- fixtures, sportsbooks, market families requested
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    outcome         text,                   -- ok | partial | failed | running
    requests_made   int         NOT NULL DEFAULT 0,
    quotes_seen     int         NOT NULL DEFAULT 0,
    quotes_written  int         NOT NULL DEFAULT 0,
    max_vendor_ts   timestamptz,            -- freshest vendor timestamp in the response
    error           jsonb
);

-- Append-only, change-only. Never UPDATE, never DELETE.
-- NOTE: odds_observation is RANGE-partitioned on captured_at. PostgreSQL requires
-- every unique constraint on a partitioned table to include the partition key, so the
-- primary key is composite (observation_id, captured_at), and any FK targeting this
-- table must include captured_at too. No ON DELETE CASCADE; no ORM relationships mapped
-- onto this table.
CREATE TABLE odds_observation (
    observation_id      bigserial,
    snapshot_id         bigint      NOT NULL REFERENCES odds_snapshot,
    vendor              text        NOT NULL,
    vendor_odds_id      text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    sportsbook          text        NOT NULL,
    market_id           text        NOT NULL,
    selection           text,
    selection_line      text,               -- over | under | null
    points              numeric(6,2),
    price_american      int,
    price_decimal       numeric(10,4),
    is_main             bool,
    grouping_key        text,
    vendor_player_id    text,
    vendor_team_id      text,
    limits              jsonb,
    availability        text        NOT NULL,-- open | suspended | pulled
    vendor_timestamp    timestamptz,
    captured_at         timestamptz NOT NULL,
    raw                 jsonb       NOT NULL,
    PRIMARY KEY (observation_id, captured_at)
) PARTITION BY RANGE (captured_at);

CREATE INDEX ON odds_observation (vendor_odds_id, captured_at DESC);
CREATE INDEX ON odds_observation (vendor_fixture_id, market_id, captured_at DESC);

-- Derived current state. Fully rebuildable; carries no unique information.
CREATE TABLE odds_market_state (
    vendor              text        NOT NULL,
    vendor_odds_id      text        NOT NULL,
    last_observation_id bigint      NOT NULL,
    last_captured_at    timestamptz NOT NULL,
    state_hash          text        NOT NULL,  -- hash(points, price, availability)
    PRIMARY KEY (vendor, vendor_odds_id),
    FOREIGN KEY (last_observation_id, last_captured_at)
        REFERENCES odds_observation (observation_id, captured_at)
);

-- Closing line, captured by policy. Missing rows are recorded, not inferred.
CREATE TABLE odds_closing_line (
    vendor              text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    vendor_odds_id      text        NOT NULL,
    observation_id      bigint,
    captured_at         timestamptz,
    seconds_before_kick int,
    status              text        NOT NULL,  -- captured | missing | market_pulled
    PRIMARY KEY (vendor, vendor_odds_id),
    FOREIGN KEY (observation_id, captured_at)
        REFERENCES odds_observation (observation_id, captured_at)
        MATCH FULL        -- observation_id and captured_at are both NULL or both set
);

-- What each book offered, per fixture, per cycle. Distinguishes
-- "book did not offer it" from "we did not ask".
CREATE TABLE market_catalog (
    vendor              text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    sportsbook          text        NOT NULL,
    market_id           text        NOT NULL,
    market_name         text        NOT NULL,
    first_seen_at       timestamptz NOT NULL,
    last_seen_at        timestamptz NOT NULL,
    PRIMARY KEY (vendor, vendor_fixture_id, sportsbook, market_id)
);
```

Partition `odds_observation` monthly. Retain raw `jsonb` indefinitely at this volume; revisit
only if it becomes a real cost.

## 4. Capture cycle

Per ADR-0003 tiers. One cycle:

1. **Resolve fixtures.** Active/upcoming NFL fixtures. Upsert into `vendor_fixture`,
   refreshing `start_date`, `status`, and `last_seen_at`. Kickoff times move; a cached
   schedule will silently mistime the closing capture.
2. **Compute due work.** For each fixture, derive its tier from
   `start_date - now()`, and select fixtures whose tier interval has elapsed since their
   last `ok` snapshot. Fixtures, not the slate, are the unit of scheduling — a Thursday
   night game and a Sunday afternoon game are in different tiers simultaneously.
3. **Resolve market scope.** Per (fixture, book), read the market catalog; refresh from the
   vendor on slow tiers or when the cache is cold. Upsert into `market_catalog`.
4. **Batch requests.** Respect endpoint limits: at most 5 combined fixture/player/team IDs
   and at most 5 sportsbooks per request. Group by market family so a failure in props does
   not lose game lines.
5. **Open the snapshot row** with the exact requested scope, before any vendor call. A crash
   mid-run then leaves visible evidence rather than a silent gap.
6. **Fetch** through the `OddsProvider` port, bounded worker pool, per-request timeout,
   retry with jittered exponential backoff on 5xx and 429 only. Never retry a 4xx contract
   error — fix the request instead.
7. **Normalize and diff.** For each quote compute
   `state_hash = hash(points, price_american, availability)`; write an `odds_observation`
   row only when it differs from `odds_market_state`, then update state.
8. **Detect pulls.** Any odds ID in `odds_market_state` that was in scope but absent from
   the response gets an observation row with `availability = 'pulled'`. Disappearance is
   information, and it is the state most often lost by naive pipelines.
9. **Close the snapshot** with `outcome`, counts, and `max_vendor_ts`. `partial` when some
   batches failed; the succeeded batches are still committed.

**Closing capture** runs as its own per-fixture job. It polls the tightest tier through
kickoff, then writes `odds_closing_line` for every odds ID seen for that fixture, marking
each `captured`, `market_pulled`, or `missing`. It never infers a close by querying "latest
observation before kickoff".

## 5. Budget model

Per cycle for the full slate, game-level markets only:

```
requests ≈ ceil(fixtures / 5) × ceil(books / 5) × market_families
16 fixtures, 7 books, 4 families  →  4 × 2 × 4  =  32 requests
```

Player props add roughly an order of magnitude, since prop markets are numerous and
player-scoped. Estimate per-slate cost from measured cycles across the tier schedule, then
set the scope-degradation thresholds from ADR-0003 against the actual plan limit. Rate limits
are enforced client-side by a token bucket per vendor, sized below the documented ceiling —
never rely on the vendor's 429 as flow control.

Instrument `requests_made` per snapshot from day one so budget forecasting comes from data
rather than arithmetic.

## 6. Validation and monitoring

Validators run after each cycle and write to a `data_quality_check` table; failures alert.

| Check | Rule | Severity |
| --- | --- | --- |
| Coverage gap | No `ok` snapshot within 2× the tier interval for any fixture | critical near kickoff |
| Closing line missing | `odds_closing_line.status = 'missing'` for any main market | critical |
| Staleness | `max_vendor_ts` older than tier tolerance | warning |
| Price sanity | American price outside ±10000, or decimal ≤ 1.0 | critical |
| Vig sanity | Two-way market no-vig total outside 0.98–1.15 | warning |
| Movement sanity | Spread moves >7 points or total >14 between adjacent observations | warning, retain both |
| Cross-source | Fallback adapter disagrees on spread by >1 point or ML by >25 cents | warning, retain both |
| Orphan quotes | Observation whose `vendor_fixture_id` is absent from `vendor_fixture` | warning |
| Schema drift | Unrecognized field or missing expected field in raw payload | warning |

Dashboard, minimum viable: snapshots per hour by tier and outcome, observations written per
hour, closing-line capture rate per slate, request count vs. budget, p95 cycle duration,
per-book last-seen freshness.

**The one alert that matters most:** closing-line capture rate below 100% for main markets.
That is unrecoverable data loss and should page, not email.

## 7. Failure modes

| Failure | Detection | Response |
| --- | --- | --- |
| Vendor 5xx / timeout | Request-level | Backoff and retry; snapshot `partial`; next tier cycle recovers |
| Rate limited | 429 | Token bucket should prevent it; on occurrence, shed to scope priority tier 1 |
| Credential expiry | 401/403 | Page immediately — silent total loss otherwise |
| Kickoff time change | Fixture refresh each cycle | Recompute tiers; closing job re-armed |
| Fixture postponed | `status` change | Suspend tiers; keep observations; no closing row |
| Market renamed at vendor | Catalog diff | Capture continues via discovery; alert on disappearance of a tier-1 market |
| Scheduler down | External heartbeat, not self-reported | Page. Nothing else detects this. |
| Writer crash mid-cycle | Snapshot stuck `running` | Sweeper marks abandoned; observations already committed remain valid |
| Duplicate concurrent cycles | Advisory lock per (tier, fixture) | Second run exits; idempotent by construction |

Design bias throughout: **fail loudly and lose nothing.** A partial capture that is honestly
labeled partial is far more valuable than a complete-looking capture with invisible holes.

## 8. Reading the store

Two functions, the only sanctioned access paths — no ad-hoc reimplementation, because this
is precisely where lookahead bias enters a project.

```python
def price_at(vendor_odds_id: str, as_of: datetime) -> PriceAtResult:
    """Latest observation at or before `as_of`, valid only if an `ok` snapshot
    covering that scope exists within tolerance. Otherwise UNKNOWN — never a
    stale price presented as current."""


def market_series(
    vendor_fixture_id: str, market_id: str, sportsbook: str, until: datetime
) -> list[Observation]:
    """Full movement series, truncated at `until`. Used for movement features;
    `until` is mandatory so a caller cannot accidentally read past kickoff."""
```

`PriceAtResult` is an explicit union: `Price(...)` | `Unknown(reason)`. Callers must handle
`Unknown`; it is not `None`, so it cannot be silently coalesced.

Derived helpers, computed at read time rather than stored: implied probability, two-way
no-vig probability, CLV in cents and in probability points, movement magnitude and
direction, and per-book vs. sharp-reference divergence.

## 9. Testing

- **Adapter contract tests** against recorded vendor fixtures (VCR-style), including a
  preseason payload with no player props and a regular-season payload with props, so the
  scope-discovery path is covered in both regimes.
- **Diff/writer unit tests:** unchanged quote writes nothing; changed price writes one row;
  vanished quote writes a `pulled` row; concurrent cycles produce no duplicates.
- **Temporal property test:** for random `as_of` values, `price_at` never returns an
  observation with `captured_at > as_of`. This is the leakage guard and it runs in CI.
- **Coverage property test:** with a synthetic failed snapshot injected, `price_at` inside
  the gap returns `Unknown`, not the pre-gap price.
- **Closing-line test:** a simulated failed final poll yields `status = 'missing'`, never a
  silently substituted earlier price.
- **Load rehearsal:** replay a simulated Sunday 1pm ET window with 9 concurrent fixtures in
  the tightest tier, asserting all closing captures land inside their window.

## 10. Build order

| Step | Deliverable | Gate |
| --- | --- | --- |
| 1 | Migrations for all six tables | Applied locally and in the deployed environment |
| 2 | `OddsProvider` port + primary adapter + recorded fixtures | Contract tests green |
| 3 | Writer with diff logic and snapshot lifecycle | Unit + property tests green |
| 4 | Orchestrator with tiered scheduling | Dry-run cycle against preseason slate |
| 5 | Deploy on a scheduler with alerting | Preseason capture running unattended |
| 6 | Closing-line job | 100% capture on a preseason slate |
| 7 | Validators + dashboard | Injected-failure drill detected and alerted |
| 8 | `price_at` / `market_series` read layer | Temporal property tests green |
| 9 | Fallback adapter + cross-source check | Disagreement alert fires on synthetic divergence |

Steps 1–6 are the Week 1 deadline. Steps 7–9 can land during the season, since they read
data rather than capture it — but step 7's coverage-gap alert should be rushed forward, as an
unnoticed outage in Week 2 is exactly the failure this whole spec exists to prevent.

## 11. Open questions

1. Sportsbook set — which books, and is a sharp reference (e.g. Pinnacle) included for
   no-vig baselining? Affects budget linearly.
2. Prop market scope for Week 1: core yardage and reception markets only, or the full prop
   surface? Recommendation: core only for Week 1, expand once the pipeline is proven.
3. Vendor plan and call ceiling, which sets the degradation thresholds in §5.
4. Deployment target for the scheduler — the capture job must run somewhere that is not a
   laptop before Week 1.
5. Whether to also capture futures (season win totals, division, MVP) at the slowest tier.
   Cheap, and enables a genuinely interesting long-horizon calibration study.
