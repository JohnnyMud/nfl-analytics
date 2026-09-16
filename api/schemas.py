"""Pydantic response models for the read API."""

from __future__ import annotations

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
    position_group: str | None
    position: str | None
    height: int | None
    weight: int | None
    headshot: str | None
    college_name: str | None
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
