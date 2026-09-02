# Brief 04 — Orchestrator and scheduler

Paste the block below into a fresh agent session. Requires briefs 01, 02, and 03 to be merged.

---

Read `AGENTS.md`, `.cursor/rules/10-odds-capture.mdc`,
`docs/adr/0003-snapshot-cadence-and-market-scope.md`, `docs/specs/odds-snapshot-pipeline.md`
(cadence and snapshot-lifecycle sections), and `docs/architecture.md` (Point-in-time discipline).

**Context.** Briefs 01–03 built the schema, the adapter (fetch + normalize + credit tracking),
and the writer (immutable snapshots with change/pull detection). None of them drive the
pipeline on a clock. This brief is the driver: it decides when to poll, calls the adapter and
writer, handles the free-tier rate budget by coarsening, and runs on a schedule.

**This is what makes the pipeline real.** Until this runs against the live API, you have
libraries, not a capture system. The first milestone is one successful live end-to-end
capture for a single game — prove that before polishing the scheduler.

**Task:** implement the cadence engine that drives the tiered, kickoff-relative snapshot
cadence, the capture cycle that composes the adapter and writer, and a minimal scheduler to
trigger it.

**Deliverables**

1. `ingest/odds/cadence.py` — pure, side-effect-free cadence logic (no clock, no DB, no
   network — fully unit-testable):
   - `Tier` enum: `coarse`, `medium`, `fine`, `none`.
   - `determine_tier(kickoff_at: datetime, now: datetime) -> Tier` per the 3-tier simplified
     Week 1 cadence: opening → T-12h = `coarse`, T-12h → T-30m = `medium`, T-30m → kickoff =
     `fine`, otherwise `none`.
   - `poll_interval(tier: Tier) -> timedelta` from config: coarse 3h, medium 15m, fine 2m.
   - `poll_due(last_poll_at: datetime | None, tier: Tier, now: datetime) -> bool` — True when
     no prior poll exists or the interval has elapsed.
   - `coarsen(tier: Tier) -> Tier` — fine → medium → coarse → none. Used when
     `RateBudgetExceeded` fires.
2. `ingest/odds/orchestrator.py` — the capture cycle:
   - `run_tick(now: datetime) -> TickStats`:
     - refresh the fixture slate if stale (`provider.list_fixtures`, cached for a configurable
       TTL, e.g. 1h — do not fetch the slate every tick; it costs a credit).
     - for each active fixture (kickoff within the capture window, e.g. next 7 days, not yet
       concluded): determine tier, then whether a poll is due.
     - for each due fixture: `writer.open_snapshot(...)` → `provider.get_odds(...)` →
       `writer.write_quotes(...)` → `writer.close_snapshot(...)`. Per-fixture try/except so
       one failure does not abort the tick.
     - on `RateBudgetExceeded` from the adapter: close the snapshot `rate_limited`, mark the
       fixture's tier as coarsened for subsequent ticks, and stop issuing new polls this tick.
     - on any other exception: close `failed` with the error recorded; do not crash the tick.
     - call `writer.sweep_abandoned(older_than=...)` at the start of the tick to recover stuck
       snapshots from a crashed prior run.
   - proactive coarsening: read the adapter's remaining monthly credit budget and, if below a
     threshold (e.g. 20%), coarsen all fixtures by one tier before issuing polls — degrade
     gracefully before the adapter is forced to raise `RateBudgetExceeded`.
3. `ingest/odds/cli.py` — a runnable entrypoint:
   - `python -m ingest.odds tick` — run one tick against the live API (this is the manual
     milestone).
   - `python -m ingest.odds loop` — run continuously, sleeping `tick_interval` (e.g. 60s)
     between ticks. Cron-friendly: `tick` is also usable directly from a crontab.
   - `ODDS_API_KEY` read from environment; never logged.
4. `tests/` — the cadence engine is pure and fully testable offline (tier boundaries,
   poll-due decisions, coarsening). Integration test of `run_tick` with a stub
   `OddsProvider` and the real writer against a test Postgres — no live network.

**Behaviors that must be tested — write these tests first**

- Tier boundaries: a fixture at T-13h is `coarse`, T-11h is `medium`, T-29m is `fine`,
  T+10m is `none`.
- `poll_due` is False within the interval, True after it, True when no prior poll.
- `coarsen(fine) == medium`, `coarsen(medium) == coarse`, `coarsen(coarse) == none`.
- `run_tick` with a stub provider returning two changed quotes writes exactly two
  observations and closes the snapshot `completed`.
- A fixture whose poll is not due is skipped — no snapshot opened.
- When the stub provider raises `RateBudgetExceeded`, the snapshot closes `rate_limited`, no
  further polls issue this tick, and the fixture's tier is coarsened for the next tick.
- A fixture whose provider call raises a generic exception closes `failed` and does not abort
  the tick for other fixtures.
- `sweep_abandoned` runs at the start of each tick.
- The fixture slate is not re-fetched when the cache is fresh.

**Constraints**

- The tick must be safe to run concurrently: acquire a Postgres advisory lock on a fixed key
  at tick start; if held, exit cleanly. Two tick processes must never double-run.
- Every tick is logged with structured output: fixtures considered, polls issued,
  observations written, `rate_limited`/`failed` counts, remaining budget. A tick that issues
  zero polls is normal (between intervals) — log it, do not alert.
- All cadence intervals, the capture window, the sportsbook set, and markets come from
  config/env, not hardcoded.
- The orchestrator is the **only** place that composes the adapter and writer. It never calls
  the vendor except through the `OddsProvider` port, and never writes the DB except through
  the writer.
- `now` is injected into the cadence engine — never read from the system clock inside
  `cadence.py`, so tests control time. The orchestrator reads the wall clock once per tick and
  passes it down.

**Scheduler: minimal now, Prefect/Dagster later**

For Week 1, run the loop on a short cron interval (every 1–2 minutes) or as the `loop` command
under a process manager (systemd, Docker Compose `restart: always`). This is deliberately
crude — it works and you can observe it. Do **not** introduce Prefect or Dagster yet; the
architecture doc names them as the right home once there are multiple cadences to coordinate
(odds tiers + the future nflverse nightly refresh). `run_tick` is structured so a future
Prefect/Dagster flow wraps it without changes.

**Watch out for**

- The kickoff-relative cadence means "active fixtures" changes every tick: a fixture enters
  the window, moves through tiers, reaches kickoff, then exits. Concluded fixtures must be
  marked and stop being polled.
- The fine tier (T-30m → kickoff) is the most research-valuable data and the most
  credit-expensive. On free this is where `RateBudgetExceeded` fires first — the coarsening
  path must degrade (fine → medium = every 15m instead of 2m) rather than drop the closing
  capture entirely. The closing line is the last fine-tier observation before kickoff.
- Clock skew: kickoff times come from the vendor's `commence_time` (UTC). Compute tiers in
  UTC, compare against `now` in UTC. Never mix timezones.
- The first run has no `last_poll_at` for any fixture — every active fixture is due
  immediately. Expect a burst on the first tick; the rate budget and coarsening handle it.

**Before writing code,** restate the task, list files, and describe how you will test the
tier-boundary and `RateBudgetExceeded`-coarsening paths. Do not start until I confirm.

**First milestone before any scheduling:** run `python -m ingest.odds tick` once by hand
against the live API for one game. Confirm one snapshot row and its observations land in the
DB. This validates the entire chain end-to-end with real data. Do not build the scheduler loop
until this works.

**Done when:** all listed behaviors have passing tests (cadence engine fully offline,
orchestrator integration with a stubbed provider + test Postgres), `mypy` is clean, and you
have run one live `tick` end-to-end and shown the resulting snapshot + observation rows.
