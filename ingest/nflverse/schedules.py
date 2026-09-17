"""Load the current-season nflverse schedule into nfl.games."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl
import psycopg

from common.settings import get_settings

# nflverse ``gametime`` is the published Eastern clock, not the host TZ.
_KICKOFF_TZ = "America/New_York"

# ADBC's Postgres COPY writer cannot ingest Polars Time (ns) or Float64 into
# numeric(4,1). Text COPY via psycopg does both. Column order matches nfl.games.
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


def _write_games(frame: pl.DataFrame) -> None:
    if frame.is_empty():
        raise RuntimeError("no games to ingest")
    buf = StringIO()
    frame.select(*_GAME_COLUMNS).write_csv(buf)
    copy_sql = (
        "COPY nfl.games ("
        + ", ".join(_GAME_COLUMNS)
        + ") FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    )
    with psycopg.connect(get_settings().postgres_url) as conn:
        with conn.cursor() as cur:
            with cur.copy(copy_sql) as copy:
                copy.write(buf.getvalue())
        conn.commit()


def main() -> None:
    ingested_at = datetime.now(UTC)
    season = nfl.get_current_season()
    games = prepare_schedules(
        nfl.load_schedules(season),
        ingested_at=ingested_at,
        season=season,
    )
    _write_games(games)


if __name__ == "__main__":
    main()
