"""Shared row factories for API tests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from infra.models import Player, Team

INGESTED_AT = datetime(2026, 9, 11, 21, 0, tzinfo=UTC)


def insert_team(
    session: Session,
    *,
    team_abbr: str,
    team_name: str,
    team_nick: str,
    team_conf: str,
    team_division: str,
    franchise_id: str = "1",
) -> Team:
    team = Team(
        team_abbr=team_abbr,
        franchise_id=franchise_id,
        team_name=team_name,
        team_nick=team_nick,
        team_conf=team_conf,
        team_division=team_division,
        team_color="#002244",
        team_color2="#69BE28",
        team_logo_espn=f"https://example.test/{team_abbr}.png",
        ingested_at=INGESTED_AT,
    )
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def insert_player(
    session: Session,
    *,
    gsis_id: str,
    display_name: str,
    latest_team: str,
    last_name: str | None = None,
    first_name: str | None = None,
    position: str | None = None,
) -> Player:
    player = Player(
        gsis_id=gsis_id,
        display_name=display_name,
        first_name=first_name,
        last_name=last_name,
        latest_team=latest_team,
        position=position,
        ingested_at=INGESTED_AT,
    )
    session.add(player)
    session.commit()
    session.refresh(player)
    return player
