"""Season summaries sum stored box scores; absent rows and null sums stay unknown."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.api.helpers import (
    insert_game,
    insert_player,
    insert_player_stat,
    insert_team,
)

RB = "00-0038134"
OTHER_RB = "00-0039139"


def _seed_teams_and_players(session: Session) -> None:
    insert_team(
        session,
        team_abbr="KC",
        team_name="Kansas City Chiefs",
        team_nick="Chiefs",
        team_conf="AFC",
        team_division="AFC West",
    )
    insert_team(
        session,
        team_abbr="DEN",
        team_name="Denver Broncos",
        team_nick="Broncos",
        team_conf="AFC",
        team_division="AFC West",
    )
    insert_player(
        session,
        gsis_id=RB,
        display_name="Kenneth Walker III",
        latest_team="KC",
        position="RB",
    )
    insert_player(
        session,
        gsis_id=OTHER_RB,
        display_name="Jahmyr Gibbs",
        latest_team="DEN",
        position="RB",
    )


def test_seasons_unknown_player_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/players/00-0000000/seasons")
    assert response.status_code == 404
    assert response.json() == {"detail": "player not found"}


def test_seasons_without_box_scores_is_empty_list(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        _seed_teams_and_players(session)

    response = api_client.get(f"/api/players/{RB}/seasons")
    assert response.status_code == 200
    assert response.json() == []


def test_seasons_sums_only_this_players_rows(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        _seed_teams_and_players(session)
        week1 = insert_game(
            session,
            game_id="2026_01_DEN_KC",
            season=2026,
            week=1,
            home_team="KC",
            away_team="DEN",
        )
        week2 = insert_game(
            session,
            game_id="2026_02_KC_DEN",
            season=2026,
            week=2,
            home_team="DEN",
            away_team="KC",
        )
        insert_player_stat(
            session,
            gsis_id=RB,
            game=week1,
            team="KC",
            opponent_team="DEN",
            carries=23,
            rushing_yards=173,
            rushing_tds=1,
            targets=3,
            receptions=2,
            receiving_yards=14,
            receiving_tds=0,
        )
        insert_player_stat(
            session,
            gsis_id=RB,
            game=week2,
            team="KC",
            opponent_team="DEN",
            carries=17,
            rushing_yards=61,
            rushing_tds=0,
            targets=1,
            receptions=1,
            receiving_yards=9,
            receiving_tds=1,
        )
        # Same games, different player: must not leak into RB's totals.
        insert_player_stat(
            session,
            gsis_id=OTHER_RB,
            game=week1,
            team="DEN",
            opponent_team="KC",
            carries=29,
            rushing_yards=156,
            rushing_tds=2,
        )

    response = api_client.get(f"/api/players/{RB}/seasons")
    assert response.status_code == 200
    assert response.json() == [
        {
            "season": 2026,
            "season_type": "REG",
            "games": 2,
            "carries": 40,
            "rushing_yards": 234,
            "rushing_tds": 1,
            "targets": 4,
            "receptions": 3,
            "receiving_yards": 23,
            "receiving_tds": 1,
            "attempts": None,
            "completions": None,
            "passing_yards": None,
            "passing_tds": None,
            "passing_interceptions": None,
        }
    ]


def test_seasons_split_by_season_and_type_newest_first(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        _seed_teams_and_players(session)
        reg_2025 = insert_game(
            session,
            game_id="2025_17_DEN_KC",
            season=2025,
            week=17,
            home_team="KC",
            away_team="DEN",
        )
        post_2025 = insert_game(
            session,
            game_id="2025_19_DEN_KC",
            season=2025,
            week=19,
            game_type="WC",
            home_team="KC",
            away_team="DEN",
        )
        reg_2026 = insert_game(
            session,
            game_id="2026_01_DEN_KC",
            season=2026,
            week=1,
            home_team="KC",
            away_team="DEN",
        )
        insert_player_stat(
            session,
            gsis_id=RB,
            game=reg_2025,
            team="KC",
            opponent_team="DEN",
            carries=10,
            rushing_yards=40,
        )
        insert_player_stat(
            session,
            gsis_id=RB,
            game=post_2025,
            team="KC",
            opponent_team="DEN",
            season_type="POST",
            carries=20,
            rushing_yards=90,
        )
        insert_player_stat(
            session,
            gsis_id=RB,
            game=reg_2026,
            team="KC",
            opponent_team="DEN",
            carries=23,
            rushing_yards=173,
        )

    response = api_client.get(f"/api/players/{RB}/seasons")
    assert response.status_code == 200
    rows = response.json()
    keys = [(row["season"], row["season_type"], row["games"]) for row in rows]
    assert keys == [(2026, "REG", 1), (2025, "POST", 1), (2025, "REG", 1)]
    by_key = {(row["season"], row["season_type"]): row for row in rows}
    assert by_key[(2025, "POST")]["rushing_yards"] == 90
    assert by_key[(2025, "REG")]["rushing_yards"] == 40


def test_seasons_all_null_column_stays_null_not_zero(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    """A stat nflverse never reported for this row must not be coalesced to 0."""
    with Session(migrated_engine) as session:
        _seed_teams_and_players(session)
        game = insert_game(
            session,
            game_id="2026_01_DEN_KC",
            season=2026,
            week=1,
            home_team="KC",
            away_team="DEN",
        )
        insert_player_stat(
            session,
            gsis_id=RB,
            game=game,
            team="KC",
            opponent_team="DEN",
            carries=23,
            rushing_yards=173,
        )

    response = api_client.get(f"/api/players/{RB}/seasons")
    body = response.json()
    assert body[0]["carries"] == 23
    assert body[0]["rushing_tds"] is None
    assert body[0]["targets"] is None


def test_get_player_exposes_header_biography(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        _seed_teams_and_players(session)

    response = api_client.get(f"/api/players/{RB}")
    assert response.status_code == 200
    body = response.json()
    for field in ("birth_date", "college_conference", "ngs_position"):
        assert field in body
