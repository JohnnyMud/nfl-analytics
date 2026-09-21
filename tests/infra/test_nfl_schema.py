"""NFL dimension and player_stats constraints and UTC round-trip."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

_DIMENSION_MIGRATION = Path("alembic/versions/0004_nfl_dimension_tables.py")
_PLAYER_STATS_MIGRATION = Path("alembic/versions/0006_nfl_player_stats.py")
_INJURIES_MIGRATION = Path("alembic/versions/0007_nfl_injuries.py")


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


def _insert_player(conn: Connection, gsis_id: str, latest_team: str) -> None:
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
            "gsis_id": gsis_id,
            "display_name": "Test Player",
            "latest_team": latest_team,
            "ingested_at": datetime(2026, 9, 2, 19, 0, 0, tzinfo=UTC),
        },
    )


def _insert_game(
    conn: Connection,
    game_id: str,
    away_team: str,
    home_team: str,
    home_qb_id: str | None = None,
) -> None:
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
            "game_id": game_id,
            "season": 2026,
            "game_type": "REG",
            "week": 1,
            "game_date": date(2026, 9, 13),
            "game_time": time(13, 0),
            "kickoff_at": datetime(2026, 9, 13, 17, 0, 0, tzinfo=UTC),
            "away_team": away_team,
            "home_team": home_team,
            "home_qb_id": home_qb_id,
            "ingested_at": datetime(2026, 9, 2, 19, 0, 0, tzinfo=UTC),
        },
    )


def test_migration_creates_empty_nfl_tables() -> None:
    source = _DIMENSION_MIGRATION.read_text()
    assert "CREATE TABLE nfl.teams" in source
    assert "CREATE TABLE nfl.players" in source
    assert "CREATE TABLE nfl.games" in source
    assert "INSERT INTO" not in source.upper()

    player_stats_source = _PLAYER_STATS_MIGRATION.read_text()
    assert "CREATE TABLE nfl.player_stats" in player_stats_source
    assert "INSERT INTO" not in player_stats_source.upper()

    injuries_source = _INJURIES_MIGRATION.read_text()
    assert "CREATE TABLE nfl.injuries" in injuries_source
    assert "INSERT INTO" not in injuries_source.upper()


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


def test_player_stats_round_trip(migrated_engine: Engine) -> None:
    ingested_at = datetime(2026, 9, 15, 3, 0, 0, tzinfo=UTC)
    gsis_id = "00-0090001"
    game_id = "2026_01_PSA_PSH"

    with migrated_engine.begin() as conn:
        _insert_team(conn, "PSA", "9101", "Player Stats Away")
        _insert_team(conn, "PSH", "9102", "Player Stats Home")
        _insert_player(conn, gsis_id, "PSH")
        _insert_game(conn, game_id, "PSA", "PSH", home_qb_id=gsis_id)
        conn.execute(
            text(
                """
                INSERT INTO nfl.player_stats (
                    gsis_id, season, week, season_type, game_id,
                    team, opponent_team, passing_yards, passing_epa,
                    ingested_at
                )
                VALUES (
                    :gsis_id, :season, :week, :season_type, :game_id,
                    :team, :opponent_team, :passing_yards, :passing_epa,
                    :ingested_at
                )
                """
            ),
            {
                "gsis_id": gsis_id,
                "season": 2026,
                "week": 1,
                "season_type": "REG",
                "game_id": game_id,
                "team": "PSH",
                "opponent_team": "PSA",
                "passing_yards": 275,
                "passing_epa": 8.5,
                "ingested_at": ingested_at,
            },
        )

    with migrated_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    gsis_id,
                    game_id,
                    passing_yards,
                    passing_epa,
                    ingested_at
                FROM nfl.player_stats
                WHERE gsis_id = :gsis_id AND game_id = :game_id
                """
            ),
            {"gsis_id": gsis_id, "game_id": game_id},
        ).one()

    assert row.ingested_at.tzinfo is not None
    assert row.ingested_at.utcoffset() is not None
    assert row.ingested_at.utcoffset().total_seconds() == 0
    assert row.ingested_at == ingested_at
    assert row.gsis_id == gsis_id
    assert row.game_id == game_id
    assert row.passing_yards == 275
    assert row.passing_epa == 8.5


def test_player_stats_reject_unknown_gsis_id(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        _insert_team(conn, "PGA", "9103", "Unknown Player Away")
        _insert_team(conn, "PGH", "9104", "Unknown Player Home")
        _insert_game(conn, "2026_01_PGA_PGH", "PGA", "PGH")

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.player_stats (
                        gsis_id, season, week, season_type, game_id,
                        team, opponent_team, ingested_at
                    )
                    VALUES (
                        :gsis_id, :season, :week, :season_type, :game_id,
                        :team, :opponent_team, :ingested_at
                    )
                    """
                ),
                {
                    "gsis_id": "00-00MISSING",
                    "season": 2026,
                    "week": 1,
                    "season_type": "REG",
                    "game_id": "2026_01_PGA_PGH",
                    "team": "PGH",
                    "opponent_team": "PGA",
                    "ingested_at": datetime(2026, 9, 15, 3, 0, 0, tzinfo=UTC),
                },
            )


def test_player_stats_reject_unknown_game_id(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        _insert_team(conn, "GGA", "9105", "Unknown Game Away")
        _insert_team(conn, "GGH", "9106", "Unknown Game Home")
        _insert_player(conn, "00-0090002", "GGH")

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.player_stats (
                        gsis_id, season, week, season_type, game_id,
                        team, opponent_team, ingested_at
                    )
                    VALUES (
                        :gsis_id, :season, :week, :season_type, :game_id,
                        :team, :opponent_team, :ingested_at
                    )
                    """
                ),
                {
                    "gsis_id": "00-0090002",
                    "season": 2026,
                    "week": 1,
                    "season_type": "REG",
                    "game_id": "2026_01_MISSING",
                    "team": "GGH",
                    "opponent_team": "GGA",
                    "ingested_at": datetime(2026, 9, 15, 3, 0, 0, tzinfo=UTC),
                },
            )


def test_player_stats_reject_unknown_team(migrated_engine: Engine) -> None:
    gsis_id = "00-0090003"
    game_id = "2026_01_TGA_TGH"
    with migrated_engine.begin() as conn:
        _insert_team(conn, "TGA", "9107", "Unknown Team Away")
        _insert_team(conn, "TGH", "9108", "Unknown Team Home")
        _insert_player(conn, gsis_id, "TGH")
        _insert_game(conn, game_id, "TGA", "TGH", home_qb_id=gsis_id)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.player_stats (
                        gsis_id, season, week, season_type, game_id,
                        team, opponent_team, ingested_at
                    )
                    VALUES (
                        :gsis_id, :season, :week, :season_type, :game_id,
                        :team, :opponent_team, :ingested_at
                    )
                    """
                ),
                {
                    "gsis_id": gsis_id,
                    "season": 2026,
                    "week": 1,
                    "season_type": "REG",
                    "game_id": game_id,
                    "team": "ZZZ",
                    "opponent_team": "TGA",
                    "ingested_at": datetime(2026, 9, 15, 3, 0, 0, tzinfo=UTC),
                },
            )


def test_injuries_round_trip(migrated_engine: Engine) -> None:
    ingested_at = datetime(2026, 9, 21, 19, 0, 0, tzinfo=UTC)
    gsis_id = "00-0091001"

    with migrated_engine.begin() as conn:
        _insert_team(conn, "INJ", "9201", "Injury Team")
        _insert_player(conn, gsis_id, "INJ")
        conn.execute(
            text(
                """
                INSERT INTO nfl.injuries (
                    season, season_type, game_type, team, week, gsis_id,
                    full_name, report_status, practice_status, ingested_at
                )
                VALUES (
                    :season, :season_type, :game_type, :team, :week, :gsis_id,
                    :full_name, :report_status, :practice_status, :ingested_at
                )
                """
            ),
            {
                "season": 2026,
                "season_type": "REG",
                "game_type": "REG",
                "team": "INJ",
                "week": 2,
                "gsis_id": gsis_id,
                "full_name": "Test Injured",
                "report_status": "Questionable",
                "practice_status": "Limited Participation in Practice",
                "ingested_at": ingested_at,
            },
        )

    with migrated_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT gsis_id, week, report_status, ingested_at
                FROM nfl.injuries
                WHERE gsis_id = :gsis_id AND season = 2026 AND week = 2
                  AND game_type = 'REG'
                """
            ),
            {"gsis_id": gsis_id},
        ).one()

    assert row.ingested_at.tzinfo is not None
    assert row.ingested_at.utcoffset() is not None
    assert row.ingested_at.utcoffset().total_seconds() == 0
    assert row.ingested_at == ingested_at
    assert row.gsis_id == gsis_id
    assert row.week == 2
    assert row.report_status == "Questionable"


def test_injuries_reject_unknown_gsis_id(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        _insert_team(conn, "IGA", "9202", "Injury Unknown Player")

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.injuries (
                        season, season_type, game_type, team, week, gsis_id,
                        ingested_at
                    )
                    VALUES (
                        :season, :season_type, :game_type, :team, :week, :gsis_id,
                        :ingested_at
                    )
                    """
                ),
                {
                    "season": 2026,
                    "season_type": "REG",
                    "game_type": "REG",
                    "team": "IGA",
                    "week": 1,
                    "gsis_id": "00-00MISSING",
                    "ingested_at": datetime(2026, 9, 21, 19, 0, 0, tzinfo=UTC),
                },
            )


def test_injuries_reject_unknown_team(migrated_engine: Engine) -> None:
    gsis_id = "00-0091002"
    with migrated_engine.begin() as conn:
        _insert_team(conn, "ITH", "9203", "Injury Known Team")
        _insert_player(conn, gsis_id, "ITH")

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO nfl.injuries (
                        season, season_type, game_type, team, week, gsis_id,
                        ingested_at
                    )
                    VALUES (
                        :season, :season_type, :game_type, :team, :week, :gsis_id,
                        :ingested_at
                    )
                    """
                ),
                {
                    "season": 2026,
                    "season_type": "REG",
                    "game_type": "REG",
                    "team": "ZZZ",
                    "week": 1,
                    "gsis_id": gsis_id,
                    "ingested_at": datetime(2026, 9, 21, 19, 0, 0, tzinfo=UTC),
                },
            )
