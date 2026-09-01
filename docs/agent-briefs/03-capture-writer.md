# Brief 03 — Capture writer and snapshot lifecycle

Paste the block below into a fresh agent session. Requires briefs 01 and 02 to be merged.

---

Read `AGENTS.md`, `.cursor/rules/10-odds-capture.mdc`,
`docs/adr/0002-immutable-bitemporal-odds-store.md`, and
`docs/specs/odds-snapshot-pipeline.md` §4.

**This is the highest-stakes code in the repository.** Odds history cannot be backfilled. A
bug here loses data permanently and usually invisibly. Prefer obvious code over clever code,
and test failure modes before happy paths.

**Task:** implement the writer that turns a batch of normalized quotes into snapshot and
observation rows.

**Deliverables**

1. `ingest/odds/writer.py` with:
   - `open_snapshot(vendor, tier, scope) -> SnapshotId` — inserts the `odds_snapshot` row
     with `outcome = 'running'` **before** any vendor call, and commits.
   - `write_quotes(snapshot_id, quotes) -> WriteStats` — the diff-and-append path.
   - `close_snapshot(snapshot_id, outcome, stats, error=None)`.
   - `sweep_abandoned(older_than)` — marks stuck `running` snapshots as abandoned.
2. State hashing: `state_hash = sha256(points, price_american, availability)`, stable across
   processes. Do not use Python's `hash()`.
3. Change detection against `odds_market_state`: insert an `odds_observation` row only when
   `state_hash` differs from the stored value, then upsert the state row in the same
   transaction.
4. Pull detection: any `vendor_odds_id` present in `odds_market_state` that was **in the
   requested scope** but absent from the response gets an observation row with
   `availability = 'pulled'`. Scope is read from the snapshot's `scope` column — do not infer
   it from the response.
5. Advisory lock keyed on `(tier, vendor_fixture_id)` so concurrent cycles cannot double-write.

**Behaviors that must be tested — write these tests first**

- Unchanged quote across two cycles writes **zero** new observation rows.
- Changed price writes exactly one row, and `odds_market_state` advances.
- Quote present in cycle 1, absent from cycle 2 while still in scope, writes exactly one
  `pulled` row.
- Quote absent from cycle 2 **and** out of scope writes nothing.
- Two concurrent `write_quotes` calls for the same fixture produce no duplicate rows.
- A crash between `open_snapshot` and `close_snapshot` leaves a `running` row that
  `sweep_abandoned` marks correctly; observations already committed remain valid.
- `write_quotes` raising mid-batch still leaves the snapshot closeable as `partial`, with
  committed rows retained.

**Constraints**

- Never `UPDATE` or `DELETE` an `odds_observation` row. Corrections are new rows.
- Never swallow an exception. Record it in the snapshot's `error` column and re-raise.
- `captured_at` is set by the writer from a single clock read per batch, so all rows in one
  cycle share it. Do not call `now()` per row.
- Store both `vendor_timestamp` and `captured_at`. They are different axes and both are
  required.
- `raw` is persisted for every observation.

**Before writing code,** restate the task, list files, and describe how you will test the
pull-detection and concurrency cases specifically. Do not start until I confirm.

**Done when:** all listed behaviors have passing tests, `mypy` is clean, and you have
explained in your summary how each of the six core invariants in `AGENTS.md` is upheld.
