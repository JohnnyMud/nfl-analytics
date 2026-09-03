"""NFL dimension table constraints and UTC round-trip."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

_MIGRATION = Path("alembic/versions/0004_nfl_dimension_tables.py")


def _insert_team(conn: Connection, abbr: str, franchise_id: str, name: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO nfl.teams (
                team_abbr, franchise_id, team_name, team_nick,
                team_conf, team_division, ingested_at
            )
            VALUES (
                :abbr, :franchise_id, :name, :nick,
                :conf, :division, :ingested_at
            )
            """
        ),
        {
            "abbr": abbr,
            "franchise_id": franchise_id,
            "name": name,
            "nick": name.split()[-1],
            "conf": "AFC",
            "division": "AFC West",
            "ingested_at": datetime(2026, 9, 2, 19, 0, 0, tzinfo=UTC),
        },
    )


def test_migration_creates_empty_nfl_tables() -> None:
    source = _MIGRATION.read_text()
    assert "CREATE TABLE nfl.teams" in source
    assert "CREATE TABLE nfl.players" in source
    assert "CREATE TABLE nfl.games" in source
    assert "INSERT INTO" not in source.upper()


def test_nfl_dimension_round_trip_and_fks(migrated_engine: Engine) -> None:
    kickoff_at = datetime(2026, 9, 13, 17, 0, 0, tzinfo=UTC)
    ingested_at = datetime(2026, 9, 2, 19, 0, 0, tzinfo=UTC)

    with migrated_engine.begin() as conn:
        _insert_team(conn, "AAA", "9001", "Test Away")
        _insert_team(conn, "HHH", "9002", "Test Home")
        conn.execute(
            text(
                """
                INSERT INTO nfl.players (
                    gsis_id, display_name, latest_team, ingested_at
                )
                VALUES (
                    :gsis_id, :display_name, :latest_team, :ingested_at
                )
                """
            ),
            {
                "gsis_id": "00-0000001",
                "display_name": "Test Quarterback",
                "latest_team": "HHH",
                "ingested_at": ingested_at,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO nfl.games (
                    game_id, season, game_type, week, game_date, game_time,
                    kickoff_at, away_team, home_team, home_qb_id,
                    ingested_at
                )
                VALUES (
                    :game_id, :season, :game_type, :week, :game_date, :game_time,
                    :kickoff_at, :away_team, :home_team, :home_qb_id,
                    :ingested_at
                )
                """
            ),
            {
                "game_id": "2026_01_AAA_HHH",
                "season": 2026,
                "game_type": "REG",
                "week": 1,
                "game_date": date(2026, 9, 13),
                "game_time": time(13, 0),
                "kickoff_at": kickoff_at,
                "away_team": "AAA",
                "home_team": "HHH",
                "home_qb_id": "00-0000001",
                "ingested_at": ingested_at,
            },
        )

    with migrated_engine.connect() as conn:
        game = conn.execute(
            text(
                """
                SELECT
                    g.kickoff_at,
                    g.ingested_at,
                    g.away_score,
                    t.franchise_id,
                    p.display_name
                FROM nfl.games AS g
                JOIN nfl.teams AS t ON t.team_abbr = g.home_team
                JOIN nfl.players AS p ON p.gsis_id = g.home_qb_id
                WHERE g.game_id = :game_id
                """
            ),
            {"game_id": "2026_01_AAA_HHH"},
        ).one()

    assert game.kickoff_at.tzinfo is not None
    assert game.kickoff_at.utcoffset() is not None
    assert game.kickoff_at.utcoffset().total_seconds() == 0
    assert game.kickoff_at == kickoff_at
    assert game.ingested_at == ingested_at
    assert game.away_score is None
    assert game.franchise_id == "9002"
    assert game.display_name == "Test Quarterback"


def test_games_reject_unknown_team(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        _insert_team(conn, "WWW", "9003", "Test Home West")

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.games (
                        game_id, season, game_type, week, game_date,
                        away_team, home_team, ingested_at
                    )
                    VALUES (
                        :game_id, :season, :game_type, :week, :game_date,
                        :away_team, :home_team, :ingested_at
                    )
                    """
                ),
                {
                    "game_id": "2026_01_ZZZ_WWW",
                    "season": 2026,
                    "game_type": "REG",
                    "week": 1,
                    "game_date": date(2026, 9, 13),
                    "away_team": "ZZZ",
                    "home_team": "WWW",
                    "ingested_at": datetime(2026, 9, 2, 19, 0, 0, tzinfo=UTC),
                },
            )


def test_relocation_abbrs_share_franchise_id(migrated_engine: Engine) -> None:
    ingested_at = datetime(2026, 9, 2, 19, 0, 0, tzinfo=UTC)
    with migrated_engine.begin() as conn:
        for abbr, name in (("LA", "Los Angeles Rams"), ("STL", "St. Louis Rams")):
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.teams (
                        team_abbr, franchise_id, team_name, team_nick,
                        team_conf, team_division, ingested_at
                    )
                    VALUES (
                        :abbr, '2510', :name, 'Rams',
                        'NFC', 'NFC West', :ingested_at
                    )
                    """
                ),
                {
                    "abbr": abbr,
                    "name": name,
                    "ingested_at": ingested_at,
                },
            )
        rows = (
            conn.execute(
                text("SELECT team_abbr FROM nfl.teams WHERE franchise_id = '2510'")
            )
            .scalars()
            .all()
        )
    assert set(rows) == {"LA", "STL"}
