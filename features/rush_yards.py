"""In-memory rush yards feature set ``rush_rb_v1``.

No database, no vendor I/O, no ``datetime.now()``. The snapshot may contain
future rows; every aggregate filters ``kickoff_at < as_of`` first.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from features.types import Known, Unknown

_REG = "REG"
_INDOOR_ROOFS = frozenset({"dome", "closed"})


class PlayerGameRow(BaseModel):
    """One player-game box score. May be the player's own or an opponent row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    season: int
    season_type: str
    kickoff_at: AwareDatetime
    rushing_yards: int
    carries: int
    team: str
    opponent_team: str
    game_id: str


class TargetContext(BaseModel):
    """Schedule context for the game being predicted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    game_id: str
    season: int
    week: int
    season_type: str
    kickoff_at: AwareDatetime
    player_team: str
    home_team: str
    away_team: str
    home_rest: int | None
    away_rest: int | None
    div_game: bool | None
    roof: str | None
    surface: str | None
    temp: int | None
    wind: int | None


class InjuryReport(BaseModel):
    """Week-level injury report treated as the pre-kickoff state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_status: str | None
    practice_status: str | None


class RushSnapshot(BaseModel):
    """Inputs for ``build_rush_rb_v1``. Future rows are allowed; the builder filters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prior_player_games: list[PlayerGameRow]
    prior_opponent_games: list[PlayerGameRow]
    target: TargetContext
    injury: InjuryReport | None = None
    depth_team: int | None = None


class RushRbV1(BaseModel):
    """One ``(gsis_id, game_id)`` feature row for feature-set ``rush_rb_v1``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_set_version: Literal["rush_rb_v1"] = "rush_rb_v1"
    gsis_id: str
    game_id: str
    as_of: datetime
    player_std_rush_yards: Known[float] | Unknown
    player_std_carries: Known[float] | Unknown
    player_std_ypc: Known[float] | Unknown
    player_last_rush_yards: Known[float] | Unknown
    player_last_carries: Known[float] | Unknown
    player_last4_rush_yards_pg: Known[float] | Unknown
    player_last4_carries_pg: Known[float] | Unknown
    player_prior_games_this_season: Known[int] | Unknown
    player_prior_season_rush_yards_pg: Known[float] | Unknown
    opp_std_rush_yards_allowed_pg: Known[float] | Unknown
    opp_last4_rush_yards_allowed_pg: Known[float] | Unknown
    is_home: Known[bool] | Unknown
    rest_days: Known[int] | Unknown
    div_game: Known[bool] | Unknown
    roof: Known[str] | Unknown
    surface: Known[str] | Unknown
    temp: Known[int] | Unknown
    wind: Known[int] | Unknown
    report_status: Known[str] | Unknown
    practice_status: Known[str] | Unknown
    depth_team: Known[int] | Unknown


@dataclass(frozen=True, slots=True)
class _OpponentTeamGame:
    game_id: str
    season: int
    season_type: str
    kickoff_at: datetime
    rush_yards_allowed: int


def build_rush_rb_v1(gsis_id: str, as_of: datetime, snapshot: RushSnapshot) -> RushRbV1:
    """Build ``rush_rb_v1`` from an in-memory snapshot.

    Raises:
        ValueError: if ``as_of`` is naive.
    """
    _require_aware_as_of(as_of)

    player_games = _player_prior_games(gsis_id, as_of, snapshot.prior_player_games)
    std_yards, std_carries, std_ypc = _player_std(player_games, snapshot.target.season)
    last_yards, last_carries = _player_last(player_games)
    last4_yards, last4_carries = _player_last4(player_games)
    prior_season_ypg = _player_prior_season_ypg(player_games, snapshot.target.season)
    opp_std, opp_last4 = _opponent_allowed(as_of, snapshot)
    is_home = _is_home(snapshot.target)
    rest_days = _rest_days(snapshot.target)

    return RushRbV1(
        gsis_id=gsis_id,
        game_id=snapshot.target.game_id,
        as_of=as_of,
        player_std_rush_yards=std_yards,
        player_std_carries=std_carries,
        player_std_ypc=std_ypc,
        player_last_rush_yards=last_yards,
        player_last_carries=last_carries,
        player_last4_rush_yards_pg=last4_yards,
        player_last4_carries_pg=last4_carries,
        player_prior_games_this_season=_player_prior_games_this_season(
            player_games, snapshot.target.season
        ),
        player_prior_season_rush_yards_pg=prior_season_ypg,
        opp_std_rush_yards_allowed_pg=opp_std,
        opp_last4_rush_yards_allowed_pg=opp_last4,
        is_home=is_home,
        rest_days=rest_days,
        div_game=_optional_bool(snapshot.target.div_game, "div_game is null"),
        roof=_optional_str(snapshot.target.roof, "roof is null"),
        surface=_optional_str(snapshot.target.surface, "surface is null"),
        temp=_weather(snapshot.target.temp, snapshot.target.roof, "temp"),
        wind=_weather(snapshot.target.wind, snapshot.target.roof, "wind"),
        report_status=_injury_status(snapshot.injury, "report_status"),
        practice_status=_injury_status(snapshot.injury, "practice_status"),
        depth_team=_depth_team(snapshot.depth_team),
    )


def _require_aware_as_of(as_of: datetime) -> None:
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")


def _prior_to(rows: list[PlayerGameRow], as_of: datetime) -> list[PlayerGameRow]:
    return [row for row in rows if row.kickoff_at < as_of]


def _player_prior_games(
    gsis_id: str, as_of: datetime, rows: list[PlayerGameRow]
) -> list[PlayerGameRow]:
    prior = [row for row in _prior_to(rows, as_of) if row.gsis_id == gsis_id]
    prior.sort(key=lambda row: (row.kickoff_at, row.game_id))
    return prior


def _is_reg(season_type: str) -> bool:
    return season_type == _REG


def _player_std(
    games: list[PlayerGameRow], season: int
) -> tuple[Known[float] | Unknown, Known[float] | Unknown, Known[float] | Unknown]:
    std_games = [
        game for game in games if game.season == season and _is_reg(game.season_type)
    ]
    if not std_games:
        missing = Unknown(reason="no prior REG game this season")
        return missing, missing, missing
    n = len(std_games)
    total_yards = sum(game.rushing_yards for game in std_games)
    total_carries = sum(game.carries for game in std_games)
    yards: Known[float] | Unknown = Known[float](value=total_yards / n)
    carries: Known[float] | Unknown = Known[float](value=total_carries / n)
    if total_carries == 0:
        ypc: Known[float] | Unknown = Unknown(reason="season-to-date carries = 0")
    else:
        ypc = Known[float](value=total_yards / total_carries)
    return yards, carries, ypc


def _player_last(
    games: list[PlayerGameRow],
) -> tuple[Known[float] | Unknown, Known[float] | Unknown]:
    if not games:
        missing = Unknown(reason="no prior played game")
        return missing, missing
    last = games[-1]
    return (
        Known[float](value=float(last.rushing_yards)),
        Known[float](value=float(last.carries)),
    )


def _player_last4(
    games: list[PlayerGameRow],
) -> tuple[Known[float] | Unknown, Known[float] | Unknown]:
    window = games[-4:]
    if not window:
        missing = Unknown(reason="no prior played game")
        return missing, missing
    n = len(window)
    return (
        Known[float](value=sum(game.rushing_yards for game in window) / n),
        Known[float](value=sum(game.carries for game in window) / n),
    )


def _player_prior_games_this_season(
    games: list[PlayerGameRow], season: int
) -> Known[int]:
    count = sum(
        1 for game in games if game.season == season and _is_reg(game.season_type)
    )
    return Known[int](value=count)


def _player_prior_season_ypg(
    games: list[PlayerGameRow], season: int
) -> Known[float] | Unknown:
    prior = [
        game
        for game in games
        if game.season == season - 1 and _is_reg(game.season_type)
    ]
    if not prior:
        return Unknown(reason="no REG box score in the prior season")
    total = sum(game.rushing_yards for game in prior)
    return Known[float](value=total / len(prior))


def _resolve_defense(target: TargetContext) -> str | None:
    if target.player_team == target.home_team:
        return target.away_team
    if target.player_team == target.away_team:
        return target.home_team
    return None


def _opponent_team_games(
    rows: list[PlayerGameRow], defense: str, as_of: datetime
) -> list[_OpponentTeamGame]:
    prior = [row for row in _prior_to(rows, as_of) if row.opponent_team == defense]
    grouped: dict[str, list[PlayerGameRow]] = defaultdict(list)
    for row in prior:
        grouped[row.game_id].append(row)

    games: list[_OpponentTeamGame] = []
    for game_id, group in grouped.items():
        first = min(group, key=lambda row: (row.kickoff_at, row.gsis_id))
        games.append(
            _OpponentTeamGame(
                game_id=game_id,
                season=first.season,
                season_type=first.season_type,
                kickoff_at=first.kickoff_at,
                rush_yards_allowed=sum(row.rushing_yards for row in group),
            )
        )
    games.sort(key=lambda game: (game.kickoff_at, game.game_id))
    return games


def _opponent_allowed(
    as_of: datetime, snapshot: RushSnapshot
) -> tuple[Known[float] | Unknown, Known[float] | Unknown]:
    defense = _resolve_defense(snapshot.target)
    if defense is None:
        missing = Unknown(reason="target team is neither home nor away")
        return missing, missing
    games = _opponent_team_games(snapshot.prior_opponent_games, defense, as_of)
    std_games = [
        game
        for game in games
        if game.season == snapshot.target.season and _is_reg(game.season_type)
    ]
    if not std_games:
        opp_std: Known[float] | Unknown = Unknown(
            reason="opponent has no prior REG game this season"
        )
    else:
        opp_std = Known[float](
            value=sum(game.rush_yards_allowed for game in std_games) / len(std_games)
        )
    last4 = games[-4:]
    if not last4:
        opp_last4: Known[float] | Unknown = Unknown(
            reason="opponent has no prior played game"
        )
    else:
        opp_last4 = Known[float](
            value=sum(game.rush_yards_allowed for game in last4) / len(last4)
        )
    return opp_std, opp_last4


def _is_home(target: TargetContext) -> Known[bool] | Unknown:
    if target.player_team == target.home_team:
        return Known[bool](value=True)
    if target.player_team == target.away_team:
        return Known[bool](value=False)
    return Unknown(reason="target team is neither home nor away")


def _rest_days(target: TargetContext) -> Known[int] | Unknown:
    if target.player_team == target.home_team:
        rest = target.home_rest
    elif target.player_team == target.away_team:
        rest = target.away_rest
    else:
        return Unknown(reason="target team is neither home nor away")
    if rest is None:
        return Unknown(reason="matching rest column is null")
    return Known[int](value=rest)


def _optional_bool(value: bool | None, reason: str) -> Known[bool] | Unknown:
    if value is None:
        return Unknown(reason=reason)
    return Known[bool](value=value)


def _optional_str(value: str | None, reason: str) -> Known[str] | Unknown:
    if value is None:
        return Unknown(reason=reason)
    return Known[str](value=value)


def _is_indoor(roof: str | None) -> bool:
    if roof is None:
        return False
    return roof.casefold() in _INDOOR_ROOFS


def _weather(value: int | None, roof: str | None, field: str) -> Known[int] | Unknown:
    if _is_indoor(roof):
        return Unknown(reason="roof is indoor (dome or closed)")
    if value is None:
        return Unknown(reason=f"{field} is null")
    return Known[int](value=value)


def _injury_status(injury: InjuryReport | None, field: str) -> Known[str] | Unknown:
    if injury is None:
        return Unknown(reason="no injury row")
    raw = injury.report_status if field == "report_status" else injury.practice_status
    if raw is None:
        return Unknown(reason=f"{field} is null")
    return Known[str](value=raw)


def _depth_team(depth_team: int | None) -> Known[int] | Unknown:
    if depth_team is None:
        return Unknown(reason="no chart row, or depth_team is null")
    return Known[int](value=depth_team)
