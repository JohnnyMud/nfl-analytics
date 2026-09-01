# 0003. Tiered snapshot cadence and market scope

Status: Accepted
Date: 2026-08-20

## Context

Capture frequency trades vendor call budget against temporal resolution. Two constraints
shape the design.

**Endpoint limits.** The current-odds endpoint accepts at most five combined
fixture/team/player IDs and at most five sportsbooks per request. A full NFL slate is
roughly 16 games; a reference book set is around seven. So one pass over game-level markets
costs about `ceil(16/5) × ceil(7/5)` = 8 requests, multiplied by the number of market
families requested. Player props expand this substantially, since prop coverage varies by
book and by market.

**Non-uniform information value.** NFL line movement is not evenly distributed in time.
Openers appear early in the week and drift slowly. The informative movement concentrates in
the final hours before kickoff, when injury news, weather, and sharp money arrive. And the
closing line — the last price before the market closes — carries outsized analytical value,
because CLV measured against it is the fastest honest read on whether a model has edge.

Uniform polling therefore wastes budget midweek and under-samples exactly where resolution
matters. Worse, a uniform hourly schedule will systematically *miss* the true close, since
the last poll may land 50 minutes before kickoff.

A third, easily overlooked constraint: **market scope is not static**. Available markets
differ by fixture, by book, and by point in the season. Preseason fixtures currently
expose game-level markets only, with no player props; prop markets appear as the regular
season approaches. A hardcoded market list would silently capture nothing when the vendor
renames a market or adds one, so scope must be discovered, not assumed.

## Decision

**Tiered cadence**, keyed off each fixture's `start_date`:

| Window relative to kickoff | Cadence | Purpose |
| --- | --- | --- |
| Opening → T-72h | every 6 hours | capture the opener and slow drift |
| T-72h → T-12h | hourly | Friday/Saturday movement |
| T-12h → T-3h | every 15 minutes | injury and lineup news |
| T-3h → T-15m | every 5 minutes | final sharp movement |
| T-15m → kickoff | every 2 minutes | closing line capture |

**Closing line is captured by policy, not by luck.** A dedicated job fires per fixture in
the final minutes before kickoff and marks the last successful observation per odds ID as
the closing price, in its own `odds_closing_line` table. Never inferred later with a
"latest before kickoff" query — that silently returns a stale price whenever the final poll
failed. If the closing capture fails, the row is recorded as missing, loudly.

**Scope is discovered every cycle, not configured.** Each run resolves active fixtures,
then resolves the market list per fixture and book, then requests only what exists. New
markets are captured automatically; renamed ones surface as scope changes rather than as
silent zero-row results. The market catalog is snapshotted to its own table so we can later
tell "the book did not offer this" from "we did not ask".

**Scope priority under budget pressure**, degraded in this order: game-level main markets
(moneyline, spread, total, team totals) → core player props (passing/rushing/receiving
yards, receptions, attempts, TDs) → alternate lines and halves/quarters → everything else.
The first tier is never dropped. Priority is config, not code.

Preseason is captured at the two slowest tiers only. It is near-worthless for modeling
(usage patterns do not carry over), but it is free end-to-end validation of the pipeline
before Week 1, which is the actual reason to run it.

## Consequences

- Temporal resolution is highest where it is analytically valuable, and the close is
  guaranteed rather than sampled.
- Sunday's 1pm ET window is the peak load: many fixtures kick simultaneously, all in their
  tightest tier at once. The job must fan out concurrently with a bounded worker pool and
  per-fixture isolation, so one slow fixture cannot delay another's close. This is the
  pipeline's hardest operational moment and its primary load test.
- Budget consumption is dominated by the last few hours, making cost predictable per slate.
- Discovery adds calls per cycle. Mitigated by caching the market catalog per
  (fixture, book) for the cycle and refreshing it on the slower tiers only.
- Tiers are declarative config, so cadence can be tuned per season without redeploying.

## Alternatives considered

**Uniform hourly polling.** Simple, but misses the close, over-samples midweek, and
under-samples the final hours. Rejected on both cost and correctness.

**Streaming / push updates.** Highest fidelity, but adds a long-lived stateful consumer,
reconnection and replay logic, and gap-recovery — a great deal of operational surface for a
component whose failure is unrecoverable. Revisit once batch capture has proven stable for
a full season.

**Poll only at fixed clock times (e.g. open, Friday, T-1h, close).** Cheapest, and enough
for CLV. But it forecloses line-movement features and movement research, which are
explicitly in scope. The tiered schedule keeps that door open.
