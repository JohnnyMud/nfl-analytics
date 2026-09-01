# Spec: Week 1 Minimum Viable Capture

Status: Active — this is the current task
Deadline: **2026-09-09, 5:20pm PT** (kickoff, NE @ SEA, Week 1 opener)
Supersedes for now: the full build order in `odds-snapshot-pipeline.md` §10
Related: ADR-0001 (why this is first), ADR-0002 (schema), ADR-0003 (cadence)

## The constraint

Roughly eight days remain before the first regular-season kickoff. The full spec is a
multi-week build. Attempting all of it and shipping something half-finished on September 9
is the worst outcome: it produces a pipeline that appears to capture and actually has holes,
which is worse than no pipeline, because holes are discovered months later during backtesting.

So this document deliberately cuts scope. **The goal is not a good pipeline. The goal is an
unbroken time series starting before Week 1.** Everything cuttable is cut.

## Scope: in

- Game-level main markets only: **moneyline, point spread, total points, team totals**
- A single sportsbook set, fixed in config
- Tiered cadence, simplified to three tiers (see below)
- Closing-line capture with explicit status
- `odds_snapshot`, `odds_observation`, `odds_market_state`, `odds_closing_line`,
  `vendor_fixture`, `market_catalog` — full schema from ADR-0002, unchanged
- Raw `jsonb` retention
- Coverage-gap and closing-line-missing alerts
- Deployed on a scheduler that is not a laptop

## Scope: out (deliberately)

| Cut | Why it's safe to cut |
| --- | --- |
| Player props | Painful to lose, but they multiply request volume and market-discovery complexity. Add in Week 2–3 once game lines are proven. Prop history from Week 1 is a real loss — accept it rather than risk the whole capture. |
| Alternate lines, halves, quarters, novelty markets | Low analytical value relative to cost. |
| Fallback adapter + cross-source checks | Second source is a quality improvement, not a capture requirement. |
| `price_at` / `market_series` read layer | Reads stored data. Can be built any time after. |
| Validation suite beyond the two critical alerts | Same reasoning. |
| Dashboard | Alerts are required; visualization is not. |
| nflverse ingestion, API, frontend, models | None of it is time-sensitive. |
| Futures | Nice-to-have, slow-moving, add later. |

**Do not cut:** the schema, the snapshot lifecycle, raw payload retention, or the two alerts.
Those are what make the captured data trustworthy later. Cutting them saves hours and costs
the season.

## Simplified cadence

Three tiers instead of five, keyed off `start_date`:

| Window | Cadence |
| --- | --- |
| Opening → T-12h | every 3 hours |
| T-12h → T-30m | every 15 minutes |
| T-30m → kickoff | every 2 minutes |

Coarser than the full design and it loses some final-hour resolution, but it is far less
scheduling logic to get right, and it still guarantees the close. Refine after Week 1 —
the schema does not change when tiers do, so this is not a decision that has to be re-made.

## Day plan

Eight days, sequenced so that the deadline-critical path finishes first and each day ends
with something that runs.

| Day | Deliverable | Done when |
| --- | --- | --- |
| 1 | Repo skeleton, Docker Postgres, Alembic, CI running lint + tests | `make test` green on an empty suite |
| 2 | Migrations for all six tables | `make migrate` applies clean; round-trip insert test passes |
| 3 | `OddsProvider` port + adapter: fixtures, markets, odds. Recorded fixtures captured from live responses | Contract tests green with no network |
| 4 | Writer: snapshot lifecycle, state hashing, change-only insert, `pulled` detection | Unit tests for all four behaviors green |
| 5 | Orchestrator with the three tiers + `make capture-dry` | Dry run prints a correct request plan for the real Week 1 slate |
| 6 | **Deploy. Start capturing.** Week 1 lines are already open — capture begins today, not on day 8 | A cycle has run unattended on schedule and written rows |
| 7 | Closing-line job + the two alerts | Injected failure produces an actual alert to your phone |
| 8 | Buffer. Watch it run. Fix what the first live day exposed | Two consecutive scheduled cycles with `outcome = 'ok'` |

Day 6 is the real deadline, not day 8. Week 1 markets are open now, so every day before
deployment is opening-line data lost. If the schedule slips, ship on day 6 with day 7's work
missing and add it after — a running pipeline without alerts beats an unlaunched pipeline
with them.

## Emergency fallback

If by day 6 the pipeline is not deployable, run the crudest possible version: a cron job that
calls the odds endpoint for the slate every 15 minutes and appends the raw JSON response to
a table with a `captured_at` column. No diffing, no normalization, no state.

It is ugly and it is 40 lines. It also preserves the irreplaceable thing, and everything else
can be reconstructed from raw payloads later. **Never let the good pipeline be the reason
there is no data.**

## Definition of done

1. Scheduled capture running unattended, not on a laptop.
2. Continuous coverage of the Week 1 slate from before openers through every kickoff.
3. `odds_closing_line` shows 100% `captured` for main markets, or explicit `missing` rows.
4. A gap or a failure sends an alert that actually reaches you.
5. Raw payloads retained, so today's normalization mistakes are fixable tomorrow.

Note what is absent: nothing about code quality, coverage percentage, or completeness. Those
matter next month. This week, only the time series matters.
