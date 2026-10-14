"""Load nflverse schedules into nfl.games.

Nightly writes the current season. Set NFLVERSE_SEASON_START/END to backfill
a range; each season is prepared and upserted separately.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings
from ingest.nflverse.seasons import seasons_from_env
from ingest.nflverse.write import upsert_frame

# nflverse ``gametime`` is the published Eastern clock, not the host TZ.
_KICKOFF_TZ = "America/New_York"

# Text COPY via psycopg (see write.upsert_frame): ADBC cannot ingest Polars
# Time (ns) or Float64 into numeric(4,1). Column order matches nfl.games.
_GAME_COLUMNS = (
    "game_id",
    "season",
    "game_type",
    "week",
    "game_date",
    "weekday",
    "game_time",
    "kickoff_at",
    "away_team",
    "home_team",
    "away_score",
    "home_score",
    "location",
    "result",
    "total",
    "overtime",
    "old_game_id",
    "gsis",
    "nfl_detail_id",
    "pfr",
    "pff",
    "espn",
    "ftn",
    "away_rest",
    "home_rest",
    "away_moneyline",
    "home_moneyline",
    "spread_line",
    "away_spread_odds",
    "home_spread_odds",
    "total_line",
    "under_odds",
    "over_odds",
    "div_game",
    "roof",
    "surface",
    "temp",
    "wind",
    "away_qb_id",
    "home_qb_id",
    "away_qb_name",
    "home_qb_name",
    "away_coach",
    "home_coach",
    "referee",
    "stadium_id",
    "stadium",
    "ingested_at",
)


def prepare_schedules(
    frame: pl.DataFrame,
    *,
    ingested_at: datetime,
    season: int,
) -> pl.DataFrame:
    """Map an nflverse schedules frame onto ``nfl.games`` for one season.

    ``load_schedules()`` defaults to every season; pass ``load_schedules(season)``
    and ``season`` here so historical games cannot leak in. ``ingested_at`` is
    supplied by the caller; this function does not read the clock.

    ``kickoff_at`` is computed from ``gameday`` + ``gametime`` in Eastern time
    and stored as UTC. A missing clock stays null rather than being guessed.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)
    return (
        frame.filter(pl.col("season") == season)
        .rename({"gameday": "game_date", "gametime": "game_time"})
        .with_columns(
            pl.col("game_date").cast(pl.String).str.to_date("%Y-%m-%d"),
            pl.col("game_time").cast(pl.String).str.to_time("%H:%M"),
            pl.col("overtime").cast(pl.Boolean),
            pl.col("div_game").cast(pl.Boolean),
            pl.lit(captured).alias("ingested_at"),
        )
        .with_columns(_kickoff_at().alias("kickoff_at"))
        .select(*_GAME_COLUMNS)
    )


def _kickoff_at() -> pl.Expr:
    return pl.datetime(
        pl.col("game_date").dt.year(),
        pl.col("game_date").dt.month(),
        pl.col("game_date").dt.day(),
        pl.col("game_time").dt.hour(),
        pl.col("game_time").dt.minute(),
        time_zone=_KICKOFF_TZ,
    ).dt.convert_time_zone("UTC")


def main() -> None:
    ingested_at = datetime.now(UTC)
    current_season = int(nfl.get_current_season())
    connection_url = get_settings().postgres_url
    for season in seasons_from_env(os.environ, current_season=current_season):
        games = prepare_schedules(
            nfl.load_schedules(season),
            ingested_at=ingested_at,
            season=season,
        )
        upsert_frame(
            games,
            table="nfl.games",
            columns=_GAME_COLUMNS,
            conflict=("game_id",),
            connection_url=connection_url,
            empty_message="no games to ingest",
        )


if __name__ == "__main__":
    main()
