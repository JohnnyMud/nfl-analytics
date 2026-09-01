# 0002. Immutable, bitemporal odds store

Status: Accepted
Date: 2026-08-20

## Context

The obvious schema for odds is a table of current prices, updated in place. That schema is
useless here: it answers "what is the line now" and nothing else. We need to answer "what
was the line at 11:00am Sunday, and had it moved since Friday, and what did it close at" —
which requires history.

The less obvious problem is distinguishing three states that a naive append-only table
conflates:

1. The price did not change between polls.
2. We polled and the book had pulled the market (no line offered).
3. We never polled, because the job failed or the market wasn't in our capture scope.

State 1 vs. 3 is the dangerous confusion. If a gap in rows can mean either "stable market"
or "we were down", then no backtest built on this data is trustworthy, and the failure is
silent — it looks like clean data. A model trained on such a table will happily learn from
prices that we merely assumed persisted.

A second issue: our identifiers are not stable at capture time. Fixtures, players, and
markets are identified by vendor IDs. Our canonical dimensions do not exist yet, and vendor
IDs can be revised. Writing our own foreign keys at ingest time would couple capture
correctness to a mapping layer that is still in flux.

## Decision

Three tables, strictly separated by what they assert.

**`odds_snapshot`** — one row per poll *attempt*, recording the scope that was requested
(fixtures, sportsbooks, market families), the wall-clock window, the outcome
(`ok` / `partial` / `failed`), request counts, and vendor freshness. This table is the
record of *coverage*: it answers "were we looking?"

**`odds_observation`** — append-only, change-only. One row per (vendor odds ID, observed
price/points) transition, with the vendor timestamp, our `captured_at`, and the
`snapshot_id` that produced it. A row is written only when price, points, or availability
differ from the last known state for that odds ID. Rows are never updated or deleted.

**`odds_market_state`** — the derived "current" view, maintained by the pipeline for cheap
reads. Fully rebuildable from the other two tables; carries no information of its own.

Reconstructing the line at time *T* is then: the latest `odds_observation` at or before *T*
for that odds ID, **valid only if** an `ok` snapshot covering that scope exists at or
before *T* within the staleness tolerance. Absent that snapshot, the answer is explicitly
"unknown", not the last stale price.

Both time axes are stored on every observation: `vendor_timestamp` (when the book's price
was set, per the vendor) and `captured_at` (when we saw it). Feature builders key off
`captured_at`, because that is the only instant we can honestly claim knowledge — using
`vendor_timestamp` invites subtle lookahead when vendor clocks or backfills disagree.

Vendor identifiers are stored verbatim (`vendor_fixture_id`, `vendor_player_id`,
`vendor_market_id`, `sportsbook`, plus the full raw payload as `jsonb`). Resolution to our
canonical `game_id` / `player_id` happens in a separate, re-runnable mapping layer.

## Consequences

- Capture cannot silently lie about coverage. Gap detection becomes a query over
  `odds_snapshot`, and a monitoring rule can alert on missing or `failed` snapshots.
- Write volume drops substantially versus storing every price at every poll, because
  unchanged lines cost nothing. Storage tracks actual market movement.
- Reads are more complex — "the price at T" is a join, not a lookup. Encapsulated in one
  well-tested function and materialized into feature tables; no ad-hoc reimplementation.
- Retaining raw `jsonb` means schema changes at the vendor never lose data. We can
  re-derive typed columns from raw rows after the fact.
- Mapping failures (an unrecognized player, a renamed market) degrade to unmapped rows
  rather than dropped captures.

## Alternatives considered

**Current-state table with updates in place.** Discards the history that is the entire
point. Rejected outright.

**Append every price at every poll.** Simpler and unambiguous about coverage, but writes
mostly duplicate rows and still needs a poll-outcome record to distinguish a failed poll
from a pulled market. Change-only plus an explicit snapshot table gets the same guarantees
for less volume.

**Postgres range types / temporal tables for validity intervals.** Elegant for
`valid_from`/`valid_to`, but interval maintenance on every write adds failure modes to the
one component that must not break. Intervals are derived in views instead.

**Resolve to canonical IDs at ingest.** Couples the irreplaceable capture path to a
mutable mapping layer. A mapping bug would then cost data, not just a re-run.
