"""SQLAlchemy mappings for nfl.teams, nfl.players, nfl.games, and nfl.player_stats.

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


class PlayerStat(Base):
    __tablename__ = "player_stats"
    __table_args__ = {"schema": "nfl"}

    gsis_id: Mapped[str] = mapped_column(
        ForeignKey("nfl.players.gsis_id"), primary_key=True
    )
    player_name: Mapped[str | None]
    player_display_name: Mapped[str | None]
    position: Mapped[str | None]
    position_group: Mapped[str | None]
    headshot_url: Mapped[str | None]
    season: Mapped[int]
    week: Mapped[int]
    season_type: Mapped[str]
    game_id: Mapped[str] = mapped_column(
        ForeignKey("nfl.games.game_id"), primary_key=True
    )
    team: Mapped[str] = mapped_column(ForeignKey("nfl.teams.team_abbr"))
    opponent_team: Mapped[str] = mapped_column(ForeignKey("nfl.teams.team_abbr"))
    completions: Mapped[int | None]
    attempts: Mapped[int | None]
    passing_yards: Mapped[int | None]
    passing_tds: Mapped[int | None]
    passing_interceptions: Mapped[int | None]
    sacks_suffered: Mapped[int | None]
    sack_yards_lost: Mapped[int | None]
    sack_fumbles: Mapped[int | None]
    sack_fumbles_lost: Mapped[int | None]
    passing_air_yards: Mapped[int | None]
    passing_yards_after_catch: Mapped[int | None]
    passing_first_downs: Mapped[int | None]
    passing_epa: Mapped[float | None]
    passing_cpoe: Mapped[float | None]
    passing_2pt_conversions: Mapped[int | None]
    pacr: Mapped[float | None]
    passing_10: Mapped[int | None]
    passing_16: Mapped[int | None]
    passing_20: Mapped[int | None]
    passing_40: Mapped[int | None]
    carries: Mapped[int | None]
    rushing_yards: Mapped[int | None]
    rushing_tds: Mapped[int | None]
    rushing_fumbles: Mapped[int | None]
    rushing_fumbles_lost: Mapped[int | None]
    rushing_first_downs: Mapped[int | None]
    rushing_epa: Mapped[float | None]
    rushing_2pt_conversions: Mapped[int | None]
    rushing_10: Mapped[int | None]
    rushing_12: Mapped[int | None]
    rushing_20: Mapped[int | None]
    rushing_40: Mapped[int | None]
    receptions: Mapped[int | None]
    targets: Mapped[int | None]
    receiving_yards: Mapped[int | None]
    receiving_tds: Mapped[int | None]
    receiving_fumbles: Mapped[int | None]
    receiving_fumbles_lost: Mapped[int | None]
    receiving_air_yards: Mapped[int | None]
    receiving_yards_after_catch: Mapped[int | None]
    receiving_first_downs: Mapped[int | None]
    receiving_epa: Mapped[float | None]
    receiving_2pt_conversions: Mapped[int | None]
    receiving_10: Mapped[int | None]
    receiving_16: Mapped[int | None]
    receiving_20: Mapped[int | None]
    receiving_40: Mapped[int | None]
    racr: Mapped[float | None]
    target_share: Mapped[float | None]
    air_yards_share: Mapped[float | None]
    wopr: Mapped[float | None]
    special_teams_tds: Mapped[int | None]
    def_tackles_solo: Mapped[int | None]
    def_tackles_with_assist: Mapped[int | None]
    def_tackle_assists: Mapped[int | None]
    def_tackles_for_loss: Mapped[int | None]
    def_tackles_for_loss_yards: Mapped[int | None]
    def_fumbles_forced: Mapped[int | None]
    def_sacks: Mapped[float | None]
    def_sack_yards: Mapped[float | None]
    def_qb_hits: Mapped[int | None]
    def_interceptions: Mapped[int | None]
    def_interception_yards: Mapped[int | None]
    def_pass_defended: Mapped[int | None]
    def_tds: Mapped[int | None]
    def_fumbles: Mapped[int | None]
    def_safeties: Mapped[int | None]
    def_punt_blocks: Mapped[int | None]
    def_pat_blocks: Mapped[int | None]
    def_fg_blocks: Mapped[int | None]
    def_2pt_atts: Mapped[int | None]
    def_2pt_made: Mapped[int | None]
    misc_yards: Mapped[int | None]
    fumble_recovery_own: Mapped[int | None]
    fumble_recovery_yards_own: Mapped[int | None]
    fumble_recovery_opp: Mapped[int | None]
    fumble_recovery_yards_opp: Mapped[int | None]
    fumble_recovery_tds: Mapped[int | None]
    penalties: Mapped[int | None]
    penalty_yards: Mapped[int | None]
    fumbles_forced_by_opp: Mapped[int | None]
    fumbles_not_forced: Mapped[int | None]
    fumbles_out_of_bounds: Mapped[int | None]
    fumbles_total: Mapped[int | None]
    fumbles_lost_total: Mapped[int | None]
    punt_returns: Mapped[int | None]
    punt_return_yards: Mapped[int | None]
    kickoff_returns: Mapped[int | None]
    kickoff_return_yards: Mapped[int | None]
    fg_made: Mapped[int | None]
    fg_att: Mapped[int | None]
    fg_missed: Mapped[int | None]
    fg_blocked: Mapped[int | None]
    fg_long: Mapped[int | None]
    fg_pct: Mapped[float | None]
    fg_made_0_19: Mapped[int | None]
    fg_made_20_29: Mapped[int | None]
    fg_made_30_39: Mapped[int | None]
    fg_made_40_49: Mapped[int | None]
    fg_made_50_59: Mapped[int | None]
    fg_made_60_: Mapped[int | None]
    fg_missed_0_19: Mapped[int | None]
    fg_missed_20_29: Mapped[int | None]
    fg_missed_30_39: Mapped[int | None]
    fg_missed_40_49: Mapped[int | None]
    fg_missed_50_59: Mapped[int | None]
    fg_missed_60_: Mapped[int | None]
    fg_made_list: Mapped[str | None]
    fg_missed_list: Mapped[str | None]
    fg_blocked_list: Mapped[str | None]
    fg_made_distance: Mapped[int | None]
    fg_missed_distance: Mapped[int | None]
    fg_blocked_distance: Mapped[int | None]
    pat_made: Mapped[int | None]
    pat_att: Mapped[int | None]
    pat_missed: Mapped[int | None]
    pat_blocked: Mapped[int | None]
    pat_pct: Mapped[float | None]
    gwfg_made: Mapped[int | None]
    gwfg_att: Mapped[int | None]
    gwfg_missed: Mapped[int | None]
    gwfg_blocked: Mapped[int | None]
    gwfg_distance: Mapped[int | None]
    pt_att: Mapped[int | None]
    pt_blocked: Mapped[int | None]
    pt_long: Mapped[int | None]
    pt_yards: Mapped[int | None]
    pt_inside_20: Mapped[int | None]
    pt_out_of_bounds: Mapped[int | None]
    pt_downed: Mapped[int | None]
    pt_touchback: Mapped[int | None]
    pt_fair_caught: Mapped[int | None]
    pt_returned: Mapped[int | None]
    pt_return_yards: Mapped[int | None]
    pt_return_tds: Mapped[int | None]
    pt_net_yards: Mapped[int | None]
    fantasy_points: Mapped[float | None]
    fantasy_points_ppr: Mapped[float | None]
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
