"""Player reads require an explicit team filter; missing ids are unknown."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.api.helpers import insert_player, insert_team


def test_list_players_requires_team_abbr(api_client: TestClient) -> None:
    response = api_client.get("/api/players")
    assert response.status_code == 422


def test_list_players_empty_team_is_empty_list(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="SEA",
            team_name="Seattle Seahawks",
            team_nick="Seahawks",
            team_conf="NFC",
            team_division="NFC West",
        )

    response = api_client.get("/api/players", params={"team_abbr": "SEA"})
    assert response.status_code == 200
    assert response.json() == []


def test_list_players_filters_to_requested_team(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="SEA",
            team_name="Seattle Seahawks",
            team_nick="Seahawks",
            team_conf="NFC",
            team_division="NFC West",
        )
        insert_team(
            session,
            team_abbr="SF",
            team_name="San Francisco 49ers",
            team_nick="49ers",
            team_conf="NFC",
            team_division="NFC West",
        )
        insert_player(
            session,
            gsis_id="00-0033873",
            display_name="Russell Wilson",
            first_name="Russell",
            last_name="Wilson",
            latest_team="SF",
            position="QB",
        )
        insert_player(
            session,
            gsis_id="00-0029263",
            display_name="DK Metcalf",
            first_name="DK",
            last_name="Metcalf",
            latest_team="SEA",
            position="WR",
        )
        insert_player(
            session,
            gsis_id="00-0033288",
            display_name="Tyler Lockett",
            first_name="Tyler",
            last_name="Lockett",
            latest_team="SEA",
            position="WR",
        )

    response = api_client.get("/api/players", params={"team_abbr": "SEA"})
    assert response.status_code == 200
    names = [row["display_name"] for row in response.json()]
    assert names == ["Tyler Lockett", "DK Metcalf"]


def test_list_players_is_the_current_roster_not_career_history(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    """Backfilled seasons leave retired players with latest_team set."""
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="KC",
            team_name="Kansas City Chiefs",
            team_nick="Chiefs",
            team_conf="AFC",
            team_division="AFC West",
        )
        insert_player(
            session,
            gsis_id="00-0033873",
            display_name="Patrick Mahomes",
            last_name="Mahomes",
            latest_team="KC",
            last_season=2026,
            status="ACT",
        )
        insert_player(
            session,
            gsis_id="00-0030615",
            display_name="Reserve Back",
            last_name="Back",
            latest_team="KC",
            last_season=2026,
            status="RES",
        )
        insert_player(
            session,
            gsis_id="00-0000001",
            display_name="Unknown Status",
            last_name="Status",
            latest_team="KC",
            last_season=2026,
            status=None,
        )
        insert_player(
            session,
            gsis_id="00-0000002",
            display_name="Released Player",
            last_name="Released",
            latest_team="KC",
            last_season=2026,
            status="CUT",
        )
        insert_player(
            session,
            gsis_id="00-0023459",
            display_name="Alex Smith",
            last_name="Smith",
            latest_team="KC",
            last_season=2017,
            status="RET",
        )
        insert_player(
            session,
            gsis_id="00-0000003",
            display_name="Last Year Only",
            last_name="Year",
            latest_team="KC",
            last_season=2025,
            status="ACT",
        )

    response = api_client.get("/api/players", params={"team_abbr": "KC"})
    assert response.status_code == 200
    names = [row["display_name"] for row in response.json()]
    assert names == ["Reserve Back", "Patrick Mahomes", "Unknown Status"]

    explicit = api_client.get(
        "/api/players", params={"team_abbr": "KC", "season": 2025}
    )
    assert [row["display_name"] for row in explicit.json()] == ["Last Year Only"]


def test_list_players_with_no_roster_loaded_is_empty(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="KC",
            team_name="Kansas City Chiefs",
            team_nick="Chiefs",
            team_conf="AFC",
            team_division="AFC West",
        )

    response = api_client.get("/api/players", params={"team_abbr": "KC"})
    assert response.status_code == 200
    assert response.json() == []


def test_get_player_unknown_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/players/00-0000000")
    assert response.status_code == 404
    assert response.json() == {"detail": "player not found"}


def test_get_player_by_gsis_id(
    api_client: TestClient,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        insert_team(
            session,
            team_abbr="SEA",
            team_name="Seattle Seahawks",
            team_nick="Seahawks",
            team_conf="NFC",
            team_division="NFC West",
        )
        insert_player(
            session,
            gsis_id="00-0029263",
            display_name="DK Metcalf",
            latest_team="SEA",
            position="WR",
        )

    response = api_client.get("/api/players/00-0029263")
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "DK Metcalf"
    assert body["latest_team"] == "SEA"
    assert "ingested_at" not in body
