"""Schema round-trip and partition coverage against a throwaway database."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

EXPECTED_PARTITIONS = {
    "odds_observation_2026_09",
    "odds_observation_2026_10",
    "odds_observation_2026_11",
    "odds_observation_2026_12",
    "odds_observation_2027_01",
    "odds_observation_2027_02",
}

MARKET_TABLES = {
    "vendor_fixture",
    "odds_snapshot",
    "odds_observation",
    "odds_market_state",
    "odds_closing_line",
    "market_catalog",
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
                INSERT INTO market.odds_snapshot (
                    vendor, tier, scope, started_at, outcome
                )
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
                INSERT INTO market.odds_observation (
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
                FROM market.odds_snapshot
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        ).one()
        observation = conn.execute(
            text(
                """
                SELECT captured_at, vendor_timestamp
                FROM market.odds_observation
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
                    JOIN pg_namespace AS n ON n.oid = parent.relnamespace
                    WHERE n.nspname = 'market'
                      AND parent.relname = 'odds_observation'
                    """
                )
            )
            .scalars()
            .all()
        )
    assert names == EXPECTED_PARTITIONS


def test_market_and_nfl_schemas_exist(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        names = set(
            conn.execute(
                text(
                    """
                    SELECT nspname
                    FROM pg_namespace
                    WHERE nspname IN ('market', 'nfl')
                    """
                )
            )
            .scalars()
            .all()
        )
    assert names == {"market", "nfl"}


def test_odds_tables_live_in_market_schema(migrated_engine: Engine) -> None:
    in_tables = text(
        """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = :schema
              AND tablename IN :tables
            """
    ).bindparams(bindparam("tables", expanding=True))
    table_names = list(MARKET_TABLES)
    with migrated_engine.connect() as conn:
        market_tables = set(
            conn.execute(
                in_tables,
                {"schema": "market", "tables": table_names},
            )
            .scalars()
            .all()
        )
        leftover_public = set(
            conn.execute(
                in_tables,
                {"schema": "public", "tables": table_names},
            )
            .scalars()
            .all()
        )
        nfl_tables = set(
            conn.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'nfl'
                    """
                )
            )
            .scalars()
            .all()
        )
        partition_schemas = set(
            conn.execute(
                text(
                    """
                    SELECT n.nspname
                    FROM pg_inherits AS i
                    JOIN pg_class AS child ON child.oid = i.inhrelid
                    JOIN pg_class AS parent ON parent.oid = i.inhparent
                    JOIN pg_namespace AS n ON n.oid = child.relnamespace
                    JOIN pg_namespace AS pn ON pn.oid = parent.relnamespace
                    WHERE pn.nspname = 'market'
                      AND parent.relname = 'odds_observation'
                    """
                )
            )
            .scalars()
            .all()
        )
    assert market_tables == MARKET_TABLES
    assert leftover_public == set()
    assert nfl_tables == {"teams", "players", "games", "player_stats"}
    assert partition_schemas == {"market"}


def test_no_timestamp_without_time_zone(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        naive = conn.execute(
            text(
                """
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE table_schema IN ('public', 'market', 'nfl')
                  AND data_type = 'timestamp without time zone'
                """
            )
        ).all()
    assert naive == []
