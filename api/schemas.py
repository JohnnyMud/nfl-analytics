"""Pydantic response models for the read API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_abbr: str
    franchise_id: str
    team_name: str
    team_nick: str
    team_conf: str
    team_division: str
    team_color: str | None
    team_color2: str | None
    team_color3: str | None
    team_color4: str | None
    team_logo_wikipedia: str | None
    team_logo_espn: str | None
    team_wordmark: str | None
    team_conference_logo: str | None
    team_league_logo: str | None
    team_logo_squared: str | None


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gsis_id: str
    display_name: str
    first_name: str | None
    last_name: str | None
    short_name: str | None
    birth_date: date | None
    position_group: str | None
    position: str | None
    ngs_position: str | None
    height: int | None
    weight: int | None
    headshot: str | None
    college_name: str | None
    college_conference: str | None
    jersey_number: str | None
    rookie_season: int | None
    last_season: int | None
    latest_team: str | None
    status: str | None
    years_of_experience: int | None
    draft_year: int | None
    draft_round: int | None
    draft_pick: int | None
    draft_team: str | None


class PlayerSeasonSummaryOut(BaseModel):
    """Box-score totals for one player over one ``(season, season_type)``.

    Sums of final box scores, so there is no ``as_of``: these are outcomes, not
    prediction inputs. ``games`` counts box-score rows that exist; a week with
    no row is not a zero game. A null sum means every stored row was null for
    that column, and the UI must render it as unknown rather than 0.
    """

    model_config = ConfigDict(from_attributes=True)

    season: int
    season_type: str
    games: int
    carries: int | None
    rushing_yards: int | None
    rushing_tds: int | None
    targets: int | None
    receptions: int | None
    receiving_yards: int | None
    receiving_tds: int | None
    attempts: int | None
    completions: int | None
    passing_yards: int | None
    passing_tds: int | None
    passing_interceptions: int | None
