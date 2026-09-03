"""SQLAlchemy mappings for nfl.teams, nfl.players, and nfl.games.

Alembic DDL is the source of truth. These classes mirror that schema for
typed reads/writes. Do not map market.odds_observation.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = {"schema": "nfl"}

    team_abbr: Mapped[str] = mapped_column(primary_key=True)
    franchise_id: Mapped[str]
    team_name: Mapped[str]
    team_nick: Mapped[str]
    team_conf: Mapped[str]
    team_division: Mapped[str]
    team_color: Mapped[str | None]
    team_color2: Mapped[str | None]
    team_color3: Mapped[str | None]
    team_color4: Mapped[str | None]
    team_logo_wikipedia: Mapped[str | None]
    team_logo_espn: Mapped[str | None]
    team_wordmark: Mapped[str | None]
    team_conference_logo: Mapped[str | None]
    team_league_logo: Mapped[str | None]
    team_logo_squared: Mapped[str | None]
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Player(Base):
    __tablename__ = "players"
    __table_args__ = {"schema": "nfl"}

    gsis_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    common_first_name: Mapped[str | None]
    first_name: Mapped[str | None]
    last_name: Mapped[str | None]
    short_name: Mapped[str | None]
    football_name: Mapped[str | None]
    suffix: Mapped[str | None]
    esb_id: Mapped[str | None]
    nfl_id: Mapped[str | None]
    pfr_id: Mapped[str | None]
    pff_id: Mapped[str | None]
    otc_id: Mapped[str | None]
    espn_id: Mapped[str | None]
    smart_id: Mapped[str | None]
    birth_date: Mapped[date | None]
    position_group: Mapped[str | None]
    position: Mapped[str | None]
    ngs_position_group: Mapped[str | None]
    ngs_position: Mapped[str | None]
    height: Mapped[int | None]
    weight: Mapped[int | None]
    headshot: Mapped[str | None]
    college_name: Mapped[str | None]
    college_conference: Mapped[str | None]
    jersey_number: Mapped[str | None]
    rookie_season: Mapped[int | None]
    last_season: Mapped[int | None]
    latest_team: Mapped[str | None] = mapped_column(ForeignKey("nfl.teams.team_abbr"))
    status: Mapped[str | None]
    ngs_status: Mapped[str | None]
    ngs_status_short_description: Mapped[str | None]
    years_of_experience: Mapped[int | None]
    pff_position: Mapped[str | None]
    pff_status: Mapped[str | None]
    draft_year: Mapped[int | None]
    draft_round: Mapped[int | None]
    draft_pick: Mapped[int | None]
    draft_team: Mapped[str | None] = mapped_column(ForeignKey("nfl.teams.team_abbr"))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Game(Base):
    __tablename__ = "games"
    __table_args__ = {"schema": "nfl"}

    game_id: Mapped[str] = mapped_column(primary_key=True)
    season: Mapped[int]
    game_type: Mapped[str]
    week: Mapped[int]
    game_date: Mapped[date]
    weekday: Mapped[str | None]
    game_time: Mapped[time | None]
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    away_team: Mapped[str] = mapped_column(ForeignKey("nfl.teams.team_abbr"))
    home_team: Mapped[str] = mapped_column(ForeignKey("nfl.teams.team_abbr"))
    away_score: Mapped[int | None]
    home_score: Mapped[int | None]
    location: Mapped[str | None]
    result: Mapped[int | None]
    total: Mapped[int | None]
    overtime: Mapped[bool | None]
    old_game_id: Mapped[str | None]
    gsis: Mapped[int | None]
    nfl_detail_id: Mapped[str | None]
    pfr: Mapped[str | None]
    pff: Mapped[int | None]
    espn: Mapped[str | None]
    ftn: Mapped[int | None]
    away_rest: Mapped[int | None]
    home_rest: Mapped[int | None]
    away_moneyline: Mapped[int | None]
    home_moneyline: Mapped[int | None]
    spread_line: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    away_spread_odds: Mapped[int | None]
    home_spread_odds: Mapped[int | None]
    total_line: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    under_odds: Mapped[int | None]
    over_odds: Mapped[int | None]
    div_game: Mapped[bool | None]
    roof: Mapped[str | None]
    surface: Mapped[str | None]
    temp: Mapped[int | None]
    wind: Mapped[int | None]
    away_qb_id: Mapped[str | None] = mapped_column(ForeignKey("nfl.players.gsis_id"))
    home_qb_id: Mapped[str | None] = mapped_column(ForeignKey("nfl.players.gsis_id"))
    away_qb_name: Mapped[str | None]
    home_qb_name: Mapped[str | None]
    away_coach: Mapped[str | None]
    home_coach: Mapped[str | None]
    referee: Mapped[str | None]
    stadium_id: Mapped[str | None]
    stadium: Mapped[str | None]
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
