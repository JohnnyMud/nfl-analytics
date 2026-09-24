"""Shared row factories for API tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from infra.models import Game, Player, PlayerStat, Team

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
    last_season: int | None = 2026,
    status: str | None = "ACT",
) -> Player:
    player = Player(
        gsis_id=gsis_id,
        display_name=display_name,
        first_name=first_name,
        last_name=last_name,
        latest_team=latest_team,
        position=position,
        last_season=last_season,
        status=status,
        ingested_at=INGESTED_AT,
    )
    session.add(player)
    session.commit()
    session.refresh(player)
    return player


def insert_game(
    session: Session,
    *,
    game_id: str,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    game_type: str = "REG",
    kickoff_at: datetime | None = None,
) -> Game:
    game = Game(
        game_id=game_id,
        season=season,
        game_type=game_type,
        week=week,
        game_date=date(season, 9, 1),
        kickoff_at=kickoff_at,
        home_team=home_team,
        away_team=away_team,
        ingested_at=INGESTED_AT,
    )
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def insert_player_stat(
    session: Session,
    *,
    gsis_id: str,
    game: Game,
    team: str,
    opponent_team: str,
    season_type: str = "REG",
    **box_score: int | None,
) -> PlayerStat:
    """One box-score row. Unspecified stat columns stay null, not 0."""
    row = PlayerStat(
        gsis_id=gsis_id,
        season=game.season,
        week=game.week,
        season_type=season_type,
        game_id=game.game_id,
        team=team,
        opponent_team=opponent_team,
        ingested_at=INGESTED_AT,
        **box_score,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
