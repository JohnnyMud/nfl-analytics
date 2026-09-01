# 0001. Capture odds before everything else

Status: Accepted
Date: 2026-08-20

## Context

The roadmap's natural order is data foundation → API → models → backtesting. Odds sit
late in that order because they only matter once there is a model to compare against the
market.

That ordering is wrong for one specific reason: **asymmetric recoverability**.

Every other dataset in this project is retroactively available. nflverse publishes
play-by-play back to 1999 and will still publish it next year; a backfill run in March
produces the same rows as a backfill run today. Odds are the opposite. An odds API returns
the market as it exists *now*. Vendors expose price history for currently-tracked
fixtures, but that access is bounded and is not a substitute for owning the series. Once a
game is played and settled, the pre-kickoff market for it is gone from our reach forever.

Two of the project's stated goals depend entirely on that history:

- comparing model probabilities against market-implied probabilities
- evaluating performance against the closing line (CLV)

CLV is the single most informative metric for whether a betting model has real edge — more
informative than short-run ROI, because it converges far faster and is much harder to fool
yourself with. A model that consistently beats the closing line has edge. A model with
positive ROI over 200 bets and no CLV signal probably got lucky.

The 2026 regular season begins in weeks. Every week that passes without capture is a week
of evaluation data that cannot be bought back at any price.

## Decision

Build and deploy the odds snapshot pipeline **first**, before the nflverse warehouse,
before the API, before any modeling. Accept a deliberately crude first version: a scheduled
job, a small immutable table, and alerting. It does not need to be pretty, integrated, or
joined to anything. It needs to be *running*.

Correctness of capture is the only quality bar that matters at this stage. Everything else
about the odds subsystem can be refactored later against stored data; the data itself
cannot be regenerated.

## Consequences

- The project's first shipped artifact is invisible to users. There is nothing to demo for
  the first stretch of work. This is accepted.
- Odds land before the game/player dimensions they should reference. The pipeline
  therefore stores vendor identifiers verbatim and defers resolution to a later mapping
  layer (see ADR-0002). Foreign keys to our own dimensions are added retroactively.
- We will capture markets we do not yet model, including preseason. Storage is cheap;
  regret is not. Over-capture is the correct error direction.
- Some captured data will be unusable due to early bugs. Mitigated by alerting on gaps
  from day one, not later.

## Alternatives considered

**Build the warehouse first, add odds in Stage 5.** Loses the 2026 season for CLV and
market-comparison analysis, which removes the most distinctive part of the project. The
backtest would be limited to nflverse's historical closing lines — useful for spread and
total context, but with no line movement, no per-book pricing, and no player props.

**Rely on the vendor's historical odds endpoint later.** It is scoped to specific odds IDs
within a single fixture and rate-limited well below bulk-extraction levels. It is a tool
for inspecting movement on a line you already know about, not a backfill mechanism.

**Buy historical odds data.** Meaningfully expensive, and player-prop history at
per-book granularity is the hardest and priciest slice to source. Capturing it ourselves
costs one scheduled job.
