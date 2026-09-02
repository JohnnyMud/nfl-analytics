"""Snapshot lifecycle and change-only observation writer.

Observations are INSERT-only. odds_market_state and odds_snapshot are the only
tables this module updates. Exceptions are never swallowed.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from ingest.odds.types import Quote, SnapshotId, SnapshotScope, WriteStats

_INSERT_OBSERVATION = text(
    """
    INSERT INTO odds_observation (
        snapshot_id,
        vendor,
        vendor_odds_id,
        vendor_fixture_id,
        sportsbook,
        market_id,
        selection,
        selection_line,
        points,
        price_american,
        price_decimal,
        is_main,
        grouping_key,
        vendor_player_id,
        vendor_team_id,
        limits,
        availability,
        vendor_timestamp,
        captured_at,
        raw
    )
    VALUES (
        :snapshot_id,
        :vendor,
        :vendor_odds_id,
        :vendor_fixture_id,
        :sportsbook,
        :market_id,
        :selection,
        :selection_line,
        :points,
        :price_american,
        :price_decimal,
        :is_main,
        :grouping_key,
        :vendor_player_id,
        :vendor_team_id,
        CAST(:limits AS jsonb),
        :availability,
        :vendor_timestamp,
        :captured_at,
        CAST(:raw AS jsonb)
    )
    RETURNING observation_id
    """
)

_UPSERT_STATE = text(
    """
    INSERT INTO odds_market_state (
        vendor,
        vendor_odds_id,
        last_observation_id,
        last_captured_at,
        state_hash
    )
    VALUES (
        :vendor,
        :vendor_odds_id,
        :last_observation_id,
        :last_captured_at,
        :state_hash
    )
    ON CONFLICT (vendor, vendor_odds_id) DO UPDATE SET
        last_observation_id = EXCLUDED.last_observation_id,
        last_captured_at = EXCLUDED.last_captured_at,
        state_hash = EXCLUDED.state_hash
    """
)

PULLED_RAW = {"reason": "absent_from_response"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def compute_state_hash(
    points: Decimal | None,
    price_american: int | None,
    availability: str,
) -> str:
    """Stable sha256 of (points, price_american, availability). Never hash()."""
    points_part = "" if points is None else format(points, "f")
    price_part = "" if price_american is None else str(price_american)
    payload = f"{points_part}|{price_part}|{availability}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lock_keys(tier: str, vendor_fixture_id: str) -> tuple[int, int]:
    digest = hashlib.sha256(f"{tier}\0{vendor_fixture_id}".encode()).digest()
    key1 = int.from_bytes(digest[:4], "big", signed=True)
    key2 = int.from_bytes(digest[4:8], "big", signed=True)
    return key1, key2


def open_snapshot(
    engine: Engine,
    vendor: str,
    tier: str,
    scope: SnapshotScope,
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> SnapshotId:
    """Insert odds_snapshot with outcome='running' and commit before returning."""
    started_at = clock()
    with engine.begin() as conn:
        snapshot_id = conn.execute(
            text(
                """
                INSERT INTO odds_snapshot (
                    vendor, tier, scope, started_at, outcome
                )
                VALUES (
                    :vendor,
                    :tier,
                    CAST(:scope AS jsonb),
                    :started_at,
                    'running'
                )
                RETURNING snapshot_id
                """
            ),
            {
                "vendor": vendor,
                "tier": tier,
                "scope": json.dumps(scope.model_dump()),
                "started_at": started_at,
            },
        ).scalar_one()
    return SnapshotId(int(snapshot_id))


def write_quotes(
    engine: Engine,
    snapshot_id: SnapshotId,
    quotes: list[Quote],
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> WriteStats:
    """Diff-and-append quotes; pull-detect from the snapshot's stored scope."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT vendor, tier, scope, outcome
                FROM odds_snapshot
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": int(snapshot_id)},
        ).one_or_none()
    if row is None:
        raise ValueError(f"snapshot {int(snapshot_id)} does not exist")
    if row.outcome != "running":
        raise ValueError(
            f"snapshot {int(snapshot_id)} is {row.outcome!r}, expected 'running'"
        )

    scope = SnapshotScope.model_validate(row.scope)
    captured_at = clock()
    quotes_by_fixture: dict[str, list[Quote]] = defaultdict(list)
    for quote in quotes:
        quotes_by_fixture[quote.vendor_fixture_id].append(quote)

    fixture_ids = sorted(set(scope.vendor_fixture_ids) | set(quotes_by_fixture))
    quotes_written = 0
    max_vendor_ts: datetime | None = None
    for quote in quotes:
        if quote.vendor_timestamp is None:
            continue
        if max_vendor_ts is None or quote.vendor_timestamp > max_vendor_ts:
            max_vendor_ts = quote.vendor_timestamp

    for fixture_id in fixture_ids:
        quotes_written += _write_fixture(
            engine,
            snapshot_id=snapshot_id,
            vendor=row.vendor,
            tier=row.tier,
            scope=scope,
            fixture_id=fixture_id,
            quotes=quotes_by_fixture[fixture_id],
            captured_at=captured_at,
            detect_pulls=fixture_id in scope.vendor_fixture_ids,
        )

    return WriteStats(
        quotes_seen=len(quotes),
        quotes_written=quotes_written,
        max_vendor_ts=max_vendor_ts,
        requests_made=0,
    )


def _write_fixture(
    engine: Engine,
    *,
    snapshot_id: SnapshotId,
    vendor: str,
    tier: str,
    scope: SnapshotScope,
    fixture_id: str,
    quotes: list[Quote],
    captured_at: datetime,
    detect_pulls: bool,
) -> int:
    """Lock, diff, insert, commit one fixture. Returns observation rows written."""
    key1, key2 = _lock_keys(tier, fixture_id)
    written = 0
    with engine.begin() as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(:key1, :key2)"),
            {"key1": key1, "key2": key2},
        )
        hashes = _load_hashes(conn, vendor, [q.vendor_odds_id for q in quotes])
        seen_ids = {q.vendor_odds_id for q in quotes}
        for quote in quotes:
            new_hash = compute_state_hash(
                quote.points, quote.price_american, quote.availability
            )
            if hashes.get(quote.vendor_odds_id) == new_hash:
                continue
            observation_id = _insert_observation(
                conn,
                snapshot_id=snapshot_id,
                vendor=vendor,
                vendor_odds_id=quote.vendor_odds_id,
                vendor_fixture_id=quote.vendor_fixture_id,
                sportsbook=quote.sportsbook,
                market_id=quote.market_id,
                selection=quote.selection,
                selection_line=quote.selection_line,
                points=quote.points,
                price_american=quote.price_american,
                price_decimal=quote.price_decimal,
                is_main=quote.is_main,
                grouping_key=None,
                vendor_player_id=quote.vendor_player_id,
                vendor_team_id=None,
                limits=None,
                availability=quote.availability,
                vendor_timestamp=quote.vendor_timestamp,
                captured_at=captured_at,
                raw=quote.raw,
            )
            _upsert_state(
                conn,
                vendor=vendor,
                vendor_odds_id=quote.vendor_odds_id,
                observation_id=observation_id,
                captured_at=captured_at,
                state_hash=new_hash,
            )
            hashes[quote.vendor_odds_id] = new_hash
            written += 1

        if detect_pulls:
            written += _write_pulls(
                conn,
                snapshot_id=snapshot_id,
                vendor=vendor,
                fixture_id=fixture_id,
                scope=scope,
                seen_ids=seen_ids,
                captured_at=captured_at,
            )
    return written


def _load_hashes(
    conn: Connection, vendor: str, vendor_odds_ids: list[str]
) -> dict[str, str]:
    if not vendor_odds_ids:
        return {}
    stmt = text(
        """
        SELECT vendor_odds_id, state_hash
        FROM odds_market_state
        WHERE vendor = :vendor AND vendor_odds_id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    rows = conn.execute(stmt, {"vendor": vendor, "ids": vendor_odds_ids}).all()
    return {row.vendor_odds_id: row.state_hash for row in rows}


def _write_pulls(
    conn: Connection,
    *,
    snapshot_id: SnapshotId,
    vendor: str,
    fixture_id: str,
    scope: SnapshotScope,
    seen_ids: set[str],
    captured_at: datetime,
) -> int:
    if not scope.sportsbooks or not scope.markets:
        return 0
    stmt = text(
        """
        SELECT
            o.vendor_odds_id,
            o.vendor_fixture_id,
            o.sportsbook,
            o.market_id,
            o.selection,
            o.selection_line,
            o.points,
            o.price_american,
            o.price_decimal,
            o.is_main,
            o.grouping_key,
            o.vendor_player_id,
            o.vendor_team_id,
            o.limits,
            s.state_hash
        FROM odds_market_state AS s
        JOIN odds_observation AS o
          ON o.observation_id = s.last_observation_id
         AND o.captured_at = s.last_captured_at
        WHERE s.vendor = :vendor
          AND o.vendor_fixture_id = :fixture_id
          AND o.sportsbook IN :sportsbooks
          AND o.market_id IN :markets
        """
    ).bindparams(
        bindparam("sportsbooks", expanding=True),
        bindparam("markets", expanding=True),
    )
    rows = conn.execute(
        stmt,
        {
            "vendor": vendor,
            "fixture_id": fixture_id,
            "sportsbooks": scope.sportsbooks,
            "markets": scope.markets,
        },
    ).all()

    written = 0
    for row in rows:
        if row.vendor_odds_id in seen_ids:
            continue
        new_hash = compute_state_hash(row.points, row.price_american, "pulled")
        if row.state_hash == new_hash:
            continue
        observation_id = _insert_observation(
            conn,
            snapshot_id=snapshot_id,
            vendor=vendor,
            vendor_odds_id=row.vendor_odds_id,
            vendor_fixture_id=row.vendor_fixture_id,
            sportsbook=row.sportsbook,
            market_id=row.market_id,
            selection=row.selection,
            selection_line=row.selection_line,
            points=row.points,
            price_american=row.price_american,
            price_decimal=row.price_decimal,
            is_main=row.is_main,
            grouping_key=row.grouping_key,
            vendor_player_id=row.vendor_player_id,
            vendor_team_id=row.vendor_team_id,
            limits=row.limits,
            availability="pulled",
            vendor_timestamp=None,
            captured_at=captured_at,
            raw=PULLED_RAW,
        )
        _upsert_state(
            conn,
            vendor=vendor,
            vendor_odds_id=row.vendor_odds_id,
            observation_id=observation_id,
            captured_at=captured_at,
            state_hash=new_hash,
        )
        written += 1
    return written


def _insert_observation(
    conn: Connection,
    *,
    snapshot_id: SnapshotId,
    vendor: str,
    vendor_odds_id: str,
    vendor_fixture_id: str,
    sportsbook: str,
    market_id: str,
    selection: str | None,
    selection_line: str | None,
    points: Decimal | None,
    price_american: int | None,
    price_decimal: Decimal | None,
    is_main: bool | None,
    grouping_key: str | None,
    vendor_player_id: str | None,
    vendor_team_id: str | None,
    limits: dict[str, Any] | None,
    availability: str,
    vendor_timestamp: datetime | None,
    captured_at: datetime,
    raw: dict[str, Any],
) -> int:
    observation_id = conn.execute(
        _INSERT_OBSERVATION,
        {
            "snapshot_id": int(snapshot_id),
            "vendor": vendor,
            "vendor_odds_id": vendor_odds_id,
            "vendor_fixture_id": vendor_fixture_id,
            "sportsbook": sportsbook,
            "market_id": market_id,
            "selection": selection,
            "selection_line": selection_line,
            "points": points,
            "price_american": price_american,
            "price_decimal": price_decimal,
            "is_main": is_main,
            "grouping_key": grouping_key,
            "vendor_player_id": vendor_player_id,
            "vendor_team_id": vendor_team_id,
            "limits": json.dumps(limits) if limits is not None else None,
            "availability": availability,
            "vendor_timestamp": vendor_timestamp,
            "captured_at": captured_at,
            "raw": json.dumps(raw),
        },
    ).scalar_one()
    return int(observation_id)


def _upsert_state(
    conn: Connection,
    *,
    vendor: str,
    vendor_odds_id: str,
    observation_id: int,
    captured_at: datetime,
    state_hash: str,
) -> None:
    conn.execute(
        _UPSERT_STATE,
        {
            "vendor": vendor,
            "vendor_odds_id": vendor_odds_id,
            "last_observation_id": observation_id,
            "last_captured_at": captured_at,
            "state_hash": state_hash,
        },
    )


def close_snapshot(
    engine: Engine,
    snapshot_id: SnapshotId,
    outcome: str,
    stats: WriteStats,
    error: dict[str, Any] | None = None,
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> None:
    """Record outcome and counts. Never touches observation rows."""
    finished_at = clock()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE odds_snapshot
                SET finished_at = :finished_at,
                    outcome = :outcome,
                    requests_made = :requests_made,
                    quotes_seen = :quotes_seen,
                    quotes_written = :quotes_written,
                    max_vendor_ts = :max_vendor_ts,
                    error = CAST(:error AS jsonb)
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {
                "snapshot_id": int(snapshot_id),
                "finished_at": finished_at,
                "outcome": outcome,
                "requests_made": stats.requests_made,
                "quotes_seen": stats.quotes_seen,
                "quotes_written": stats.quotes_written,
                "max_vendor_ts": stats.max_vendor_ts,
                "error": json.dumps(error) if error is not None else None,
            },
        )


def sweep_abandoned(
    engine: Engine,
    older_than: datetime,
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> int:
    """Mark stuck running snapshots as abandoned. Committed observations stay."""
    finished_at = clock()
    error = json.dumps(
        {
            "reason": "abandoned",
            "older_than": older_than.isoformat(),
        }
    )
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE odds_snapshot
                SET outcome = 'abandoned',
                    finished_at = :finished_at,
                    error = CAST(:error AS jsonb)
                WHERE outcome = 'running'
                  AND started_at < :older_than
                """
            ),
            {
                "finished_at": finished_at,
                "error": error,
                "older_than": older_than,
            },
        )
    return int(result.rowcount)
