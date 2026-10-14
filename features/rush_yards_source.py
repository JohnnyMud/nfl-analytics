"""Point-in-time ``RushSnapshot`` assembly from ``nfl.*`` rows.

This is the only module in ``features/`` that reads the database, and it only
reads. ``load_rush_history`` does bulk SELECTs bounded by ``kickoff_before``;
``RushSnapshotIndex`` is pure and hands ``build_rush_rb_v1`` only rows whose
``kickoff_at`` is strictly before the target ``as_of``. The builder filters
again, so a bug in either layer alone cannot leak a same-day or later game.

Team codes are compared by ``nfl.teams.franchise_id``. nflverse box scores use
the current club code (``LV``, ``LAC``) for seasons the schedule still labels
``OAK`` / ``SD``; comparing raw strings would make every such game look like
the player is on neither side.

Injury reports and depth charts are week-grain or derived-instant sources. See
``docs/specs/rush-yards-phase1.md`` for how much pre-kickoff trust they get.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Connection

from features.rush_yards import (
    InjuryReport,
    PlayerGameRow,
    RushSnapshot,
    TargetContext,
)

RB_POSITION_GROUP = "RB"
REG = "REG"
DEPTH_CHART_RB_SLOTS: tuple[str, ...] = ("RB", "HB")
DEPTH_CHART_MAX_AGE = timedelta(days=10)


class BoxScore(BaseModel):
    """One player-game box score joined to its kickoff. A label for its own game."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    game_id: str
    season: int
    week: int
    season_type: str
    position_group: str | None
    kickoff_at: AwareDatetime
    team: str
    opponent_team: str
    rushing_yards: int
    carries: int


class TeamGameAllowed(BaseModel):
    """Rushing yards and carries one defense allowed in one game, summed in SQL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    game_id: str
    season: int
    season_type: str
    kickoff_at: AwareDatetime
    offense: str
    defense: str
    rushing_yards: int
    carries: int


class ScheduledGame(BaseModel):
    """Schedule context. ``temp`` / ``wind`` are game actuals when present."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    game_id: str
    season: int
    week: int
    game_type: str
    kickoff_at: AwareDatetime
    home_team: str
    away_team: str
    home_rest: int | None
    away_rest: int | None
    div_game: bool | None
    roof: str | None
    surface: str | None
    temp: int | None
    wind: int | None


class InjuryRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    season: int
    week: int
    game_type: str
    report_status: str | None
    practice_status: str | None


class DepthRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    team: str
    snapshot_at: AwareDatetime
    depth_rank: int | None


class RushHistory(BaseModel):
    """Everything a run may read. Facts all kicked off before ``kickoff_before``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kickoff_before: AwareDatetime
    box_scores: tuple[BoxScore, ...]
    team_games: tuple[TeamGameAllowed, ...]
    games: tuple[ScheduledGame, ...]
    injuries: tuple[InjuryRow, ...]
    depth: tuple[DepthRow, ...]
    franchise_of: dict[str, str]


class RushTarget(BaseModel):
    """One player-game to build features for. ``team`` is the player's club then."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    game_id: str
    team: str
    as_of: AwareDatetime


def load_rush_history(
    conn: Connection,
    *,
    season_start: int,
    season_end: int,
    kickoff_before: datetime,
) -> RushHistory:
    """Read the rows a rush_rb_v1 run needs. SELECT only.

    Box scores, team-game totals, and depth snapshots are bounded by
    ``kickoff_before`` (exclusive) in SQL. Schedule rows are not bounded, so
    upcoming games can be targets; only pregame columns plus the stated
    ``temp`` / ``wind`` actuals are read from them, never scores.
    ``season_start - 1`` is loaded so prior-season features exist.
    """
    if kickoff_before.tzinfo is None or kickoff_before.utcoffset() is None:
        raise ValueError("kickoff_before must be timezone-aware")
    if season_start > season_end:
        raise ValueError("season_start must be <= season_end")
    params = {
        "first": season_start - 1,
        "last": season_end,
        "before": kickoff_before,
    }

    box_scores = tuple(
        BoxScore.model_validate(dict(row))
        for row in conn.execute(_BOX_SCORES_SQL, params).mappings()
    )
    team_games = tuple(
        TeamGameAllowed.model_validate(dict(row))
        for row in conn.execute(_TEAM_GAMES_SQL, params).mappings()
    )
    games = tuple(
        ScheduledGame.model_validate(dict(row))
        for row in conn.execute(_GAMES_SQL, params).mappings()
    )
    injuries = tuple(
        InjuryRow.model_validate(dict(row))
        for row in conn.execute(_INJURIES_SQL, params).mappings()
    )
    depth = tuple(
        DepthRow.model_validate(dict(row))
        for row in conn.execute(
            _DEPTH_SQL, {**params, "slots": list(DEPTH_CHART_RB_SLOTS)}
        ).mappings()
    )
    franchise_of = {
        str(row["team_abbr"]): str(row["franchise_id"])
        for row in conn.execute(_TEAMS_SQL).mappings()
    }
    return RushHistory(
        kickoff_before=kickoff_before,
        box_scores=box_scores,
        team_games=team_games,
        games=games,
        injuries=injuries,
        depth=depth,
        franchise_of=franchise_of,
    )


def rb_population(
    history: RushHistory, *, season_start: int, season_end: int
) -> list[BoxScore]:
    """REG RB box scores in the scored seasons, oldest kickoff first."""
    rows = [
        row
        for row in history.box_scores
        if row.position_group == RB_POSITION_GROUP
        and row.season_type == REG
        and season_start <= row.season <= season_end
    ]
    rows.sort(key=lambda row: (row.kickoff_at, row.game_id, row.gsis_id))
    return rows


class RushSnapshotIndex:
    """Pure lookup from ``RushHistory`` to per-target snapshots."""

    def __init__(self, history: RushHistory) -> None:
        self._franchise_of = history.franchise_of
        self._games = {game.game_id: game for game in history.games}

        by_player: dict[str, list[PlayerGameRow]] = defaultdict(list)
        for row in history.box_scores:
            by_player[row.gsis_id].append(self._player_row(row))
        self._player_rows = _sorted_by_kickoff(by_player)

        by_defense: dict[str, list[PlayerGameRow]] = defaultdict(list)
        for team_game in history.team_games:
            allowed = self._team_game_row(team_game)
            by_defense[allowed.opponent_team].append(allowed)
        self._defense_rows = _sorted_by_kickoff(by_defense)

        self._injuries = {
            (row.gsis_id, row.season, row.week, row.game_type): row
            for row in history.injuries
        }

        depth: dict[str, list[DepthRow]] = defaultdict(list)
        for depth_row in history.depth:
            depth[depth_row.gsis_id].append(depth_row)
        self._depth = {
            gsis_id: sorted(rows, key=lambda row: row.snapshot_at)
            for gsis_id, rows in depth.items()
        }

    def snapshot(self, target: RushTarget) -> RushSnapshot:
        """Snapshot for ``target`` with only rows that kicked off before ``as_of``.

        An ``as_of`` later than ``kickoff_before`` (an upcoming game) sees
        nothing past ``kickoff_before``: missing information, never lookahead.

        Raises:
            ValueError: ``game_id`` is not in the loaded schedule.
        """
        as_of = target.as_of
        game = self._games.get(target.game_id)
        if game is None:
            raise ValueError(f"game {target.game_id!r} is not in the loaded schedule")

        player_team = self._franchise(target.team)
        home = self._franchise(game.home_team)
        away = self._franchise(game.away_team)
        defense = away if player_team == home else home if player_team == away else None

        prior_player = _before(self._player_rows.get(target.gsis_id, []), as_of)
        prior_defense = (
            _before(self._defense_rows.get(defense, []), as_of)
            if defense is not None
            else []
        )
        injury = self._injuries.get(
            (target.gsis_id, game.season, game.week, game.game_type)
        )
        return RushSnapshot(
            prior_player_games=prior_player,
            prior_opponent_games=prior_defense,
            target=TargetContext(
                game_id=game.game_id,
                season=game.season,
                week=game.week,
                season_type=REG if game.game_type == REG else "POST",
                kickoff_at=game.kickoff_at,
                player_team=player_team,
                home_team=home,
                away_team=away,
                home_rest=game.home_rest,
                away_rest=game.away_rest,
                div_game=game.div_game,
                roof=game.roof,
                surface=game.surface,
                temp=game.temp,
                wind=game.wind,
            ),
            injury=(
                InjuryReport(
                    report_status=injury.report_status,
                    practice_status=injury.practice_status,
                )
                if injury is not None
                else None
            ),
            depth_team=self._depth_rank(target.gsis_id, player_team, as_of),
        )

    def _franchise(self, team: str) -> str:
        return self._franchise_of.get(team, team)

    def _player_row(self, row: BoxScore) -> PlayerGameRow:
        return PlayerGameRow(
            gsis_id=row.gsis_id,
            season=row.season,
            season_type=row.season_type,
            kickoff_at=row.kickoff_at,
            rushing_yards=row.rushing_yards,
            carries=row.carries,
            team=self._franchise(row.team),
            opponent_team=self._franchise(row.opponent_team),
            game_id=row.game_id,
        )

    def _team_game_row(self, row: TeamGameAllowed) -> PlayerGameRow:
        return PlayerGameRow(
            gsis_id=f"team-game:{row.offense}",
            season=row.season,
            season_type=row.season_type,
            kickoff_at=row.kickoff_at,
            rushing_yards=row.rushing_yards,
            carries=row.carries,
            team=self._franchise(row.offense),
            opponent_team=self._franchise(row.defense),
            game_id=row.game_id,
        )

    def _depth_rank(self, gsis_id: str, team: str, as_of: datetime) -> int | None:
        """Best RB rank in the latest club snapshot at or before ``as_of``.

        Week-only seasons store the club kickoff as ``snapshot_at``, so ``<=``
        is what reaches that week's chart. Older than 10 days is no chart.
        """
        candidates = [
            row
            for row in self._depth.get(gsis_id, [])
            if row.snapshot_at <= as_of
            and row.snapshot_at > as_of - DEPTH_CHART_MAX_AGE
            and self._franchise(row.team) == team
        ]
        if not candidates:
            return None
        latest = max(row.snapshot_at for row in candidates)
        ranks = [
            row.depth_rank
            for row in candidates
            if row.snapshot_at == latest and row.depth_rank is not None
        ]
        return min(ranks) if ranks else None


def _sorted_by_kickoff(
    groups: dict[str, list[PlayerGameRow]],
) -> dict[str, list[PlayerGameRow]]:
    return {
        key: sorted(rows, key=lambda row: (row.kickoff_at, row.game_id))
        for key, rows in groups.items()
    }


def _before(rows: Sequence[PlayerGameRow], as_of: datetime) -> list[PlayerGameRow]:
    """Rows strictly before ``as_of``. ``rows`` must be sorted by kickoff."""
    cut = bisect_left([row.kickoff_at for row in rows], as_of)
    return list(rows[:cut])


def targets_from_box_scores(rows: Iterable[BoxScore]) -> list[RushTarget]:
    """Historical targets: the player's club and kickoff from the row itself."""
    return [
        RushTarget(
            gsis_id=row.gsis_id,
            game_id=row.game_id,
            team=row.team,
            as_of=row.kickoff_at,
        )
        for row in rows
    ]


def week_first_kickoff(conn: Connection, *, season: int, week: int) -> datetime | None:
    """Earliest REG kickoff in a week: the data cutoff for predicting it."""
    value = conn.execute(
        text(
            """
            SELECT min(kickoff_at) FROM nfl.games
            WHERE season = :season AND week = :week AND game_type = 'REG'
            """
        ),
        {"season": season, "week": week},
    ).scalar_one_or_none()
    if value is None:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise TypeError("nfl.games.kickoff_at must be a timezone-aware timestamp")
    return value


def week_games(history: RushHistory, *, season: int, week: int) -> list[ScheduledGame]:
    """Scheduled REG games for one week, earliest kickoff first."""
    games = [
        game
        for game in history.games
        if game.season == season and game.week == week and game.game_type == REG
    ]
    games.sort(key=lambda game: (game.kickoff_at, game.game_id))
    return games


def upcoming_targets(
    history: RushHistory, games: Sequence[ScheduledGame]
) -> list[RushTarget]:
    """RBs to predict for games that have not been loaded as box scores.

    A club's backs are the RB box scores from that club's most recent game
    this season that kicked off before ``history.kickoff_before``. A club with
    no game yet this season (week 1) gets no targets rather than a guess
    carried over from last season's roster.
    """
    franchise_of = history.franchise_of
    latest_game: dict[tuple[str, int], tuple[datetime, str]] = {}
    for row in history.box_scores:
        key = (franchise_of.get(row.team, row.team), row.season)
        seen = latest_game.get(key)
        if seen is None or (row.kickoff_at, row.game_id) > seen:
            latest_game[key] = (row.kickoff_at, row.game_id)

    targets: list[RushTarget] = []
    for game in games:
        for side in (game.home_team, game.away_team):
            franchise = franchise_of.get(side, side)
            last = latest_game.get((franchise, game.season))
            if last is None:
                continue
            backs = sorted(
                {
                    row.gsis_id
                    for row in history.box_scores
                    if row.game_id == last[1]
                    and franchise_of.get(row.team, row.team) == franchise
                    and row.position_group == RB_POSITION_GROUP
                }
            )
            targets.extend(
                RushTarget(
                    gsis_id=gsis_id,
                    game_id=game.game_id,
                    team=side,
                    as_of=game.kickoff_at,
                )
                for gsis_id in backs
            )
    return targets


_BOX_SCORES_SQL = text(
    """
    SELECT ps.gsis_id, ps.game_id, ps.season, ps.week, ps.season_type,
           ps.position_group, g.kickoff_at, ps.team, ps.opponent_team,
           ps.rushing_yards, ps.carries
    FROM nfl.player_stats AS ps
    JOIN nfl.games AS g ON g.game_id = ps.game_id
    WHERE g.kickoff_at IS NOT NULL
      AND g.kickoff_at < :before
      AND ps.season BETWEEN :first AND :last
      AND ps.rushing_yards IS NOT NULL
      AND ps.carries IS NOT NULL
      AND ps.gsis_id IN (
          SELECT DISTINCT gsis_id FROM nfl.player_stats
          WHERE position_group = 'RB' AND season BETWEEN :first AND :last
      )
    """
)

_TEAM_GAMES_SQL = text(
    """
    SELECT ps.game_id, ps.season, ps.season_type, g.kickoff_at,
           ps.team AS offense, ps.opponent_team AS defense,
           COALESCE(SUM(ps.rushing_yards), 0)::int AS rushing_yards,
           COALESCE(SUM(ps.carries), 0)::int AS carries
    FROM nfl.player_stats AS ps
    JOIN nfl.games AS g ON g.game_id = ps.game_id
    WHERE g.kickoff_at IS NOT NULL
      AND g.kickoff_at < :before
      AND ps.season BETWEEN :first AND :last
    GROUP BY ps.game_id, ps.season, ps.season_type, g.kickoff_at,
             ps.team, ps.opponent_team
    """
)

_GAMES_SQL = text(
    """
    SELECT game_id, season, week, game_type, kickoff_at, home_team, away_team,
           home_rest, away_rest, div_game, roof, surface, temp, wind
    FROM nfl.games
    WHERE kickoff_at IS NOT NULL
      AND season BETWEEN :first AND :last
    """
)

_INJURIES_SQL = text(
    """
    SELECT gsis_id, season, week, game_type, report_status, practice_status
    FROM nfl.injuries
    WHERE season BETWEEN :first AND :last
    """
)

_DEPTH_SQL = text(
    """
    SELECT gsis_id, team, snapshot_at, depth_rank
    FROM nfl.depth_charts
    WHERE position = ANY(:slots)
      AND snapshot_at < :before
      AND snapshot_at >= make_timestamptz(:first, 1, 1, 0, 0, 0, 'UTC')
    """
)

_TEAMS_SQL = text("SELECT team_abbr, franchise_id FROM nfl.teams")
