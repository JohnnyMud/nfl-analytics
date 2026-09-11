# Brief 01 — Repo foundation and schema

Paste the block below into a fresh agent session.

---

Read `AGENTS.md` and `docs/specs/week1-minimum-capture.md` before starting. Skim
`docs/adr/0002-immutable-bitemporal-odds-store.md` for the schema rationale and
`docs/specs/odds-snapshot-pipeline.md` §3 for the DDL.

**Task:** set up the repository foundation and the database schema. No business logic yet.

**Deliverables**

1. Project skeleton with the layer directories from `AGENTS.md` (`ingest/`, `transform/`,
  `features/`, `models/`, `backtest/`, `api/`, `web/`, `infra/`), each with an
   `__init__.py` and a one-line docstring stating its responsibility.
2. `pyproject.toml`: Python 3.12, ruff, mypy (strict on `features/` and `models/`), pytest,
  pydantic v2, sqlalchemy 2.0, alembic, httpx, structlog. Nothing else — do not add
   libraries speculatively.
3. `docker-compose.yml` with Postgres 16 and a named volume.
4. Alembic initialized, plus one migration creating the six tables from
  `odds-snapshot-pipeline.md` §3: `vendor_fixture`, `odds_snapshot`, `odds_observation`,
   `odds_market_state`, `odds_closing_line`, `market_catalog`. Include the indexes listed
   there. Partition `odds_observation` by month on `captured_at`, with partitions for
   2026-08 through 2027-02.
5. A `Makefile` with exactly the targets listed in `AGENTS.md`.
6. GitHub Actions workflow running `make lint` and `make test` on push.
7. `structlog` configured for JSON output, with a single `get_logger` helper.
8. One test that applies migrations against a throwaway database, inserts a snapshot and a
  linked observation, reads them back, and asserts the timestamps round-trip as UTC-aware.

**Constraints**

- All timestamp columns are `timestamptz`. No `timestamp without time zone` anywhere.
- `odds_observation` gets no `UPDATE`/`DELETE` path. Do not add ORM cascade deletes to it.
- Vendor identifier columns are prefixed `vendor_`; our own `game_id` is nullable.
- Keep `raw jsonb NOT NULL` on every table that has it in the spec.
- No secrets in the repo. Database URL comes from `DATABASE_URL`.

**Before writing code,** restate the task, list the files you will create, and flag anything
in the spec that is ambiguous or that you think is wrong. Do not start until I confirm.

**Done when:** `make db-up && make migrate && make test && make lint` all succeed from a
clean clone, and CI is green.

## Resolved decisions (answers to the agent's questions)

These supersede any conflicting reading of the references above.

1. **Partitioned-table PK/FK (real Postgres bug, fixed in spec §3).** The primary key on
  `odds_observation` is now composite `(observation_id, captured_at)` because PG requires
   unique constraints on a partitioned table to include the partition key. Both referencing
   tables already carry `captured_at`:
  - `odds_market_state`: FK `(last_observation_id, last_captured_at)` →
  `odds_observation (observation_id, captured_at)`
  - `odds_closing_line`: FK `(observation_id, captured_at)` → `odds_observation (observation_id, captured_at)` with `MATCH FULL`, so the pair is
  both-NULL (capture failed) or both-set. No `ON DELETE CASCADE` anywhere. Do not map
   `odds_observation` as an ORM model — the absence of a relationship is the guarantee.
2. **psycopg[binary] is approved** as required plumbing (DBAPI driver), not a speculative
  library. Add it. Nothing else extra — no testcontainers, no dotenv.
3. `get_logger` **lives in** `common/logging.py`, a new cross-cutting package, not in
  `ingest/`. Putting logging in `ingest/` would force `features/` and `models/` to import
   upward across layer boundaries. `common/` is imported downward only by all layers.
   Add `common/` to the layer directory list with an `__init__.py`.
4. **CI Postgres service approved.** Add a `postgres:16` service to the GitHub Actions
  workflow, point `DATABASE_URL` at it, and run `make test` (which includes the round-trip
   migration test). No extra Python libraries.
5. **No DEFAULT partition.** Only the seven months (2026-08 through 2027-02). Inserts
  outside that range fail loudly, which matches the capture invariants. Additionally, add a
   CI test asserting the expected partitions exist, so a missing partition fails the build
   before it fails in production. Before February 2027, add a migration creating
   2027-03 onward — this is a known follow-up, not part of this brief.
6. `make capture-dry` **is a stub** that prints "capture not implemented" and exits 0.
  `make setup` creates the venv, installs the project with a `dev` extra
   (ruff/mypy/pytest), and installs pre-commit. Pre-commit itself is not a project
   dependency.
7. **No SQLAlchemy ORM in this change.** Use Core/SQL against the migrated schema for the
  round-trip test. The writer brief may add mappings later, but prefer Core for
   `odds_observation` writes even then — append-heavy with `jsonb` gains little from ORM
   mapping, and staying in Core keeps the no-cascade guarantee structural.
8. **Skip** `web/__init__.py`**.** `web/` will be a React/TypeScript app, not a Python package.
  Create it as a plain directory with a placeholder `README.md` ("React + TypeScript frontend;
   not yet initialized"), no `__init__.py`.

