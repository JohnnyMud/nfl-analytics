"""Player dimension reads and per-player box-score summaries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select

from api.deps import DbSession
from api.schemas import PlayerOut, PlayerSeasonSummaryOut
from infra.models import Player, PlayerStat

router = APIRouter()

# Roster rows nflverse keeps on the seasonal file for players no longer on a
# club. The current-season loader drops them; older backfilled rows may not.
_OFF_ROSTER_STATUSES = ("CUT", "RET")

# Box-score columns summed into a season row. Order here is the response
# field order; keep it aligned with PlayerSeasonSummaryOut.
_SUMMED_COLUMNS = (
    PlayerStat.carries,
    PlayerStat.rushing_yards,
    PlayerStat.rushing_tds,
    PlayerStat.targets,
    PlayerStat.receptions,
    PlayerStat.receiving_yards,
    PlayerStat.receiving_tds,
    PlayerStat.attempts,
    PlayerStat.completions,
    PlayerStat.passing_yards,
    PlayerStat.passing_tds,
    PlayerStat.passing_interceptions,
)


@router.get("/players", response_model=list[PlayerOut])
def list_players(
    team_abbr: str, db: DbSession, season: int | None = None
) -> list[Player]:
    """Players on ``team_abbr``'s roster for ``season``.

    ``nfl.players`` holds one row per person, with ``latest_team`` and
    ``last_season`` current as of the last roster ingest. Filtering on
    ``latest_team`` alone returns everyone whose career ended with this club,
    so the roster season is required too. When ``season`` is omitted, the
    newest ``last_season`` in the table is used: the latest roster loaded, not
    the wall clock. A null ``status`` is kept; unknown is not off-roster.
    """
    if season is None:
        season = db.scalar(select(func.max(Player.last_season)))
        if season is None:
            return []
    stmt = (
        select(Player)
        .where(
            Player.latest_team == team_abbr,
            Player.last_season == season,
            or_(
                Player.status.is_(None),
                Player.status.not_in(_OFF_ROSTER_STATUSES),
            ),
        )
        .order_by(Player.last_name, Player.first_name, Player.display_name)
    )
    return list(db.scalars(stmt).all())


@router.get("/players/{gsis_id}", response_model=PlayerOut)
def get_player(gsis_id: str, db: DbSession) -> Player:
    player = db.get(Player, gsis_id)
    if player is None:
        raise HTTPException(status_code=404, detail="player not found")
    return player


@router.get(
    "/players/{gsis_id}/seasons",
    response_model=list[PlayerSeasonSummaryOut],
)
def list_player_seasons(gsis_id: str, db: DbSession) -> list[PlayerSeasonSummaryOut]:
    """Season totals from final box scores, newest season first.

    An empty list means no box-score rows are loaded for this player. SQL
    ``SUM`` of an all-null column is null and is passed through as null.
    """
    if db.get(Player, gsis_id) is None:
        raise HTTPException(status_code=404, detail="player not found")

    stmt = (
        select(
            PlayerStat.season,
            PlayerStat.season_type,
            func.count().label("games"),
            *(func.sum(column).label(column.key) for column in _SUMMED_COLUMNS),
        )
        .where(PlayerStat.gsis_id == gsis_id)
        .group_by(PlayerStat.season, PlayerStat.season_type)
        .order_by(PlayerStat.season.desc(), PlayerStat.season_type)
    )
    return [
        PlayerSeasonSummaryOut.model_validate(dict(row._mapping))
        for row in db.execute(stmt).all()
    ]
