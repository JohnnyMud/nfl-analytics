"""Writer failure-mode tests. Require DATABASE_URL (throwaway migrated DB)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Thread

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.odds import writer
from ingest.odds.types import Quote, SnapshotScope, WriteStats
from ingest.odds.writer import (
    close_snapshot,
    compute_state_hash,
    open_snapshot,
    sweep_abandoned,
    write_quotes,
)

VENDOR = "the_odds_api"
TIER = "hourly"
CAPTURED_AT = datetime(2026, 9, 6, 17, 0, tzinfo=UTC)
VENDOR_TS = datetime(2026, 9, 6, 16, 55, tzinfo=UTC)

SCOPE_FX1 = SnapshotScope(
    vendor_fixture_ids=["fx-1"],
    sportsbooks=["draftkings"],
    markets=["h2h"],
)
SCOPE_FX2 = SnapshotScope(
    vendor_fixture_ids=["fx-2"],
    sportsbooks=["draftkings"],
    markets=["h2h"],
)
SCOPE_BOTH = SnapshotScope(
    vendor_fixture_ids=["fx-1", "fx-2"],
    sportsbooks=["draftkings"],
    markets=["h2h"],
)


def _clock() -> datetime:
    return CAPTURED_AT


def make_quote(**overrides: object) -> Quote:
    values: dict[str, object] = {
        "vendor": VENDOR,
        "vendor_odds_id": "odds-1",
        "vendor_fixture_id": "fx-1",
        "sportsbook": "draftkings",
        "market_id": "h2h",
        "selection": "Seattle Seahawks",
        "selection_line": None,
        "points": None,
        "price_american": -110,
        "price_decimal": Decimal("1.9091"),
        "is_main": True,
        "vendor_player_id": None,
        "vendor_timestamp": VENDOR_TS,
        "availability": "open",
        "raw": {"quote": 1},
    }
    values.update(overrides)
    return Quote.model_validate(values)


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Engine]:
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                """
                TRUNCATE market.odds_market_state, market.odds_closing_line,
                         market.odds_observation, market.odds_snapshot
                RESTART IDENTITY CASCADE
                """
            )
        )
    yield migrated_engine


def _observation_count(engine: Engine, vendor_odds_id: str = "odds-1") -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM market.odds_observation
                    WHERE vendor_odds_id = :vendor_odds_id
                    """
                ),
                {"vendor_odds_id": vendor_odds_id},
            ).scalar_one()
        )


def _state_hash(engine: Engine, vendor_odds_id: str = "odds-1") -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT state_hash FROM market.odds_market_state
                WHERE vendor = :vendor AND vendor_odds_id = :vendor_odds_id
                """
            ),
            {"vendor": VENDOR, "vendor_odds_id": vendor_odds_id},
        ).scalar_one_or_none()


def _snapshot_outcome(engine: Engine, snapshot_id: int) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT outcome FROM market.odds_snapshot WHERE snapshot_id = :id"),
            {"id": snapshot_id},
        ).scalar_one()


def _close_ok(engine: Engine, snapshot_id: int) -> None:
    close_snapshot(
        engine,
        snapshot_id,
        "ok",
        WriteStats(quotes_seen=1, quotes_written=1, max_vendor_ts=VENDOR_TS),
        clock=_clock,
    )


def test_unchanged_quote_writes_zero_rows_on_second_cycle(db: Engine) -> None:
    quote = make_quote()
    snap_a = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    write_quotes(db, snap_a, [quote], clock=_clock)
    _close_ok(db, snap_a)

    hash_after_first = _state_hash(db)
    assert _observation_count(db) == 1

    snap_b = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    stats = write_quotes(db, snap_b, [quote], clock=_clock)
    close_snapshot(db, snap_b, "ok", stats, clock=_clock)

    assert stats.quotes_seen == 1
    assert stats.quotes_written == 0
    assert _observation_count(db) == 1
    assert _state_hash(db) == hash_after_first


def test_changed_price_writes_one_row_and_advances_state(db: Engine) -> None:
    first = make_quote(price_american=-110)
    snap_a = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    write_quotes(db, snap_a, [first], clock=_clock)
    _close_ok(db, snap_a)

    hash_before = _state_hash(db)
    second = make_quote(price_american=-115, raw={"quote": 2})
    snap_b = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    stats = write_quotes(db, snap_b, [second], clock=_clock)
    close_snapshot(db, snap_b, "ok", stats, clock=_clock)

    assert stats.quotes_written == 1
    assert _observation_count(db) == 2
    hash_after = _state_hash(db)
    assert hash_after is not None
    assert hash_after != hash_before
    assert hash_after == compute_state_hash(None, -115, "open")


def test_in_scope_disappearance_writes_one_pulled_row(db: Engine) -> None:
    quote = make_quote()
    snap_a = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    write_quotes(db, snap_a, [quote], clock=_clock)
    _close_ok(db, snap_a)

    hash_before = _state_hash(db)
    snap_b = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    stats = write_quotes(db, snap_b, [], clock=_clock)
    close_snapshot(db, snap_b, "ok", stats, clock=_clock)

    assert stats.quotes_seen == 0
    assert stats.quotes_written == 1
    assert _observation_count(db) == 2

    with db.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT availability, raw, snapshot_id, vendor_timestamp
                FROM market.odds_observation
                WHERE vendor_odds_id = 'odds-1'
                ORDER BY observation_id DESC
                LIMIT 1
                """
            )
        ).one()

    assert row.availability == "pulled"
    assert row.raw == {"reason": "absent_from_response"}
    assert row.snapshot_id == snap_b
    assert row.vendor_timestamp is None
    hash_after = _state_hash(db)
    assert hash_after is not None
    assert hash_after != hash_before
    assert hash_after == compute_state_hash(None, -110, "pulled")


def test_out_of_scope_absence_writes_nothing(db: Engine) -> None:
    quote = make_quote()
    snap_a = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    write_quotes(db, snap_a, [quote], clock=_clock)
    _close_ok(db, snap_a)

    hash_before = _state_hash(db)
    snap_b = open_snapshot(db, VENDOR, TIER, SCOPE_FX2, clock=_clock)
    stats = write_quotes(db, snap_b, [], clock=_clock)
    close_snapshot(db, snap_b, "ok", stats, clock=_clock)

    assert stats.quotes_written == 0
    assert _observation_count(db) == 1
    assert _state_hash(db) == hash_before


def test_concurrent_write_quotes_produce_no_duplicate_rows(db: Engine) -> None:
    quote = make_quote()
    snap_a = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    snap_b = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)

    barrier = Barrier(2)
    errors: list[BaseException] = []

    def run(snapshot_id: int) -> None:
        try:
            barrier.wait(timeout=5)
            write_quotes(db, snapshot_id, [quote], clock=_clock)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        Thread(target=run, args=(snap_a,)),
        Thread(target=run, args=(snap_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert _observation_count(db) == 1
    with db.connect() as conn:
        state_rows = conn.execute(
            text("SELECT COUNT(*) FROM market.odds_market_state")
        ).scalar_one()
    assert int(state_rows) == 1


def test_sweep_abandoned_marks_running_and_keeps_observations(db: Engine) -> None:
    quote = make_quote()
    snap = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    write_quotes(db, snap, [quote], clock=_clock)

    assert _snapshot_outcome(db, snap) == "running"
    marked = sweep_abandoned(
        db, older_than=CAPTURED_AT + timedelta(seconds=1), clock=_clock
    )
    assert marked == 1
    assert _snapshot_outcome(db, snap) == "abandoned"
    assert _observation_count(db) == 1

    with db.connect() as conn:
        error = conn.execute(
            text("SELECT error FROM market.odds_snapshot WHERE snapshot_id = :id"),
            {"id": snap},
        ).scalar_one()
    assert error is not None
    assert error["reason"] == "abandoned"


def test_write_quotes_raise_mid_batch_keeps_committed_rows(
    db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    quote_a = make_quote(vendor_odds_id="odds-1", vendor_fixture_id="fx-1")
    quote_b = make_quote(vendor_odds_id="odds-2", vendor_fixture_id="fx-2")
    snap = open_snapshot(db, VENDOR, TIER, SCOPE_BOTH, clock=_clock)

    original = writer._write_fixture
    calls = {"n": 0}

    def wrapper(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("injected failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(writer, "_write_fixture", wrapper)

    with pytest.raises(RuntimeError, match="injected failure"):
        write_quotes(db, snap, [quote_a, quote_b], clock=_clock)

    assert _observation_count(db, "odds-1") == 1
    assert _observation_count(db, "odds-2") == 0
    assert _snapshot_outcome(db, snap) == "running"

    close_snapshot(
        db,
        snap,
        "partial",
        WriteStats(quotes_seen=2, quotes_written=1, max_vendor_ts=VENDOR_TS),
        error={"reason": "injected failure"},
        clock=_clock,
    )
    assert _snapshot_outcome(db, snap) == "partial"
    assert _observation_count(db, "odds-1") == 1


def test_batch_rows_share_a_single_captured_at(db: Engine) -> None:
    quotes = [
        make_quote(vendor_odds_id="odds-1", selection="Seattle Seahawks"),
        make_quote(
            vendor_odds_id="odds-2",
            selection="New England Patriots",
            price_american=120,
        ),
    ]
    snap = open_snapshot(db, VENDOR, TIER, SCOPE_FX1, clock=_clock)
    write_quotes(db, snap, quotes, clock=_clock)

    with db.connect() as conn:
        stamps = (
            conn.execute(
                text(
                    """
                SELECT DISTINCT captured_at
                FROM market.odds_observation
                WHERE snapshot_id = :id
                """
                ),
                {"id": snap},
            )
            .scalars()
            .all()
        )
    assert stamps == [CAPTURED_AT]
