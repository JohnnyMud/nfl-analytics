# AGENTS.md

Read this before writing code. Keep it short — if it grows past ~150 lines, move detail
into `docs/` and link it instead.

## What this project is

An NFL analytics and predictive modeling platform: a stats database, an exploration UI, and
a research environment for evaluating predictive models against the betting market.

The differentiator is not predictions. It is being able to answer "what actually matters
when predicting this game or player?" — and to check whether a claimed edge existed
historically. Code that produces a prediction without a traceable, reproducible basis is
not useful here.

## Current state

Design phase. First component under construction: the **odds snapshot pipeline**.

- Active task spec: `docs/specs/week1-minimum-capture.md` (deadline-scoped)
- Active modeling spec: `docs/specs/rush-yards-phase1.md` (RB rush yards, walk-forward)
- Full design: `docs/specs/odds-snapshot-pipeline.md`
- Decisions: `docs/adr/`

## Non-negotiable invariants

Violating any of these is a bug even if tests pass and the feature works.

1. **No lookahead. Ever.** Any function producing a value used for prediction takes an
   explicit `as_of` timestamp and must be physically unable to read rows with
   `captured_at > as_of`. Never `now()` inside a feature builder.
2. **Unknown is not null.** When data is unavailable for a requested time, return an
   explicit `Unknown(reason)` variant. Never return the most recent value as a substitute,
   and never `None` — it gets coalesced silently.
3. **Captured data is immutable.** `odds_observation` is append-only. No `UPDATE`, no
   `DELETE`, no "fixing" rows in place. Corrections are new rows.
4. **Coverage is asserted separately from values.** A missing row means "unknown", never
   "unchanged". Every poll attempt is recorded whether or not it succeeded.
5. **Fail loudly, lose nothing.** Partial results labeled partial beat complete-looking
   results with invisible holes. Never swallow an exception in the capture path.
6. **Store raw payloads.** Every external response is persisted as `jsonb` alongside typed
   columns, so typed columns can be re-derived after a schema change.
7. **Time is UTC, `timestamptz`, always.** No naive datetimes cross a function boundary.
   Kickoff-relative logic is computed, never hardcoded to a local time.

## Conventions

- Python 3.12+. `ruff` for lint and format, `mypy --strict` on `features/` and `models/`.
- Pydantic v2 for all boundary types. No bare dicts across module boundaries.
- SQLAlchemy 2.0 style. Migrations via Alembic; never edit an applied migration.
- Secrets from environment only. If you find a credential in the repo, stop and flag it.
- Vendor identifiers are stored verbatim and prefixed `vendor_*`. Our own IDs are resolved
  in a separate mapping layer and are nullable by design.
- Tests colocated as `tests/` mirroring package structure. `pytest`, no network in unit
  tests — vendor responses come from recorded fixtures in `tests/fixtures/vendor/`.

## Layer boundaries

```
ingest/     external I/O only. Knows about vendors. Knows nothing about models.
transform/  SQL. bronze -> silver -> marts.
features/   point-in-time builders. Pure functions of (entity, as_of).
models/     training + prediction. Reads features, never raw tables.
backtest/   walk-forward harness. Reads stored predictions, never re-predicts inline.
api/        FastAPI. Reads precomputed rows only. No feature computation, no inference.
web/        React + TS. Not a Python package. No __init__.py.
common/     cross-cutting: logging, config, errors, shared types. Imported downward only.
```

Cross-layer imports go downward only. `api/` importing from `models/` is a design error.

## What NOT to do without asking

- Do not add a dependency to solve something the standard library handles.
- Do not introduce a new service, queue, or database. The stack is decided in
  `docs/architecture.md`; changing it needs a new ADR.
- Do not refactor the capture path while it is capturing live data. Capture correctness
  outranks code beauty for the duration of the season.
- Do not use random k-fold cross-validation on game data. Time-aware splits only.
- Do not "improve" a model's reported accuracy by changing the evaluation protocol.
- Do not write a prediction to the DB without the model version and feature-set version
  that produced it.

## Commands

```bash
make setup        # venv + deps + pre-commit
make db-up        # local postgres via docker compose
make migrate      # alembic upgrade head
make test         # pytest
make lint         # ruff + mypy
make capture-dry  # one capture cycle, no writes, prints planned requests
```

## Definition of done

A change is done when: tests cover the failure mode (not just the happy path), types pass
strict checking, the temporal property test still passes, and — for anything in the capture
path — an injected failure produces a visible alert rather than silent success.
