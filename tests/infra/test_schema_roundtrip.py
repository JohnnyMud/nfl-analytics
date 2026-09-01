"""Schema round-trip and partition coverage against a throwaway database."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

EXPECTED_PARTITIONS = {
    "odds_observation_2026_08",
    "odds_observation_2026_09",
    "odds_observation_2026_10",
    "odds_observation_2026_11",
    "odds_observation_2026_12",
    "odds_observation_2027_01",
    "odds_observation_2027_02",
}


def test_snapshot_and_observation_timestamps_round_trip_utc(
    migrated_engine: Engine,
) -> None:
    started_at = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    captured_at = datetime(2026, 9, 1, 12, 0, 1, tzinfo=UTC)

    with migrated_engine.begin() as conn:
        snapshot_id = conn.execute(
            text(
                """
                INSERT INTO odds_snapshot (vendor, tier, scope, started_at, outcome)
                VALUES (
                    :vendor,
                    :tier,
                    CAST(:scope AS jsonb),
                    :started_at,
                    :outcome
                )
                RETURNING snapshot_id
                """
            ),
            {
                "vendor": "opticodds",
                "tier": "opening",
                "scope": '{"fixtures": ["fx-1"]}',
                "started_at": started_at,
                "outcome": "ok",
            },
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO odds_observation (
                    snapshot_id,
                    vendor,
                    vendor_odds_id,
                    vendor_fixture_id,
                    sportsbook,
                    market_id,
                    availability,
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
                    :availability,
                    :captured_at,
                    CAST(:raw AS jsonb)
                )
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "vendor": "opticodds",
                "vendor_odds_id": "odds-1",
                "vendor_fixture_id": "fx-1",
                "sportsbook": "pinnacle",
                "market_id": "moneyline",
                "availability": "open",
                "captured_at": captured_at,
                "raw": '{"quote": 1}',
            },
        )

    with migrated_engine.connect() as conn:
        snapshot = conn.execute(
            text(
                """
                SELECT started_at
                FROM odds_snapshot
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        ).one()
        observation = conn.execute(
            text(
                """
                SELECT captured_at, vendor_timestamp
                FROM odds_observation
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        ).one()

    assert snapshot.started_at.tzinfo is not None
    assert snapshot.started_at.utcoffset() is not None
    assert snapshot.started_at.utcoffset().total_seconds() == 0
    assert snapshot.started_at == started_at

    assert observation.captured_at.tzinfo is not None
    assert observation.captured_at.utcoffset() is not None
    assert observation.captured_at.utcoffset().total_seconds() == 0
    assert observation.captured_at == captured_at
    assert observation.vendor_timestamp is None


def test_odds_observation_monthly_partitions_exist(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        names = set(
            conn.execute(
                text(
                    """
                    SELECT child.relname
                    FROM pg_inherits AS i
                    JOIN pg_class AS child ON child.oid = i.inhrelid
                    JOIN pg_class AS parent ON parent.oid = i.inhparent
                    WHERE parent.relname = 'odds_observation'
                    """
                )
            )
            .scalars()
            .all()
        )
    assert names == EXPECTED_PARTITIONS


def test_no_timestamp_without_time_zone(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        naive = conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND data_type = 'timestamp without time zone'
                """
            )
        ).all()
    assert naive == []
