"""Load nflverse injury reports into nfl.injuries.

Nightly writes the current season. Set NFLVERSE_SEASON_START/END to backfill
a range; each season is prepared and upserted separately.
``delete_absent_for_season`` stays scoped to the season being written.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings
from ingest.nflverse.seasons import seasons_from_env
from ingest.nflverse.write import upsert_frame

_INJURY_COLUMNS = (
    "season",
    "season_type",
    "game_type",
    "team",
    "week",
    "gsis_id",
    "position",
    "full_name",
    "first_name",
    "last_name",
    "report_primary_injury",
    "report_secondary_injury",
    "report_status",
    "practice_primary_injury",
    "practice_secondary_injury",
    "practice_status",
    "ingested_at",
)


def prepare_injuries(
    frame: pl.DataFrame,
    *,
    ingested_at: datetime,
    season: int,
) -> pl.DataFrame:
    """Map an nflverse injuries frame onto ``nfl.injuries``.

    Use ``load_injuries(season)``. ``seasons=True`` is every year since 2009;
    pass ``season`` here so historical weeks cannot leak in.

    ``ingested_at`` is supplied by the caller; this function does not read the
    clock. Rows without ``gsis_id`` cannot be keyed and are omitted.
    These are weekly published reports, not timestamped snapshots.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)
    return (
        frame.filter(pl.col("season") == season)
        .with_columns(pl.col("gsis_id").cast(pl.String))
        .filter(pl.col("gsis_id").is_not_null() & (pl.col("gsis_id") != ""))
        .with_columns(pl.lit(captured).alias("ingested_at"))
        .select(*_INJURY_COLUMNS)
    )


def main() -> None:
    ingested_at = datetime.now(UTC)
    current_season = int(nfl.get_current_season())
    connection_url = get_settings().postgres_url
    for season in seasons_from_env(os.environ, current_season=current_season):
        injuries = prepare_injuries(
            nfl.load_injuries(season),
            ingested_at=ingested_at,
            season=season,
        )
        upsert_frame(
            injuries,
            table="nfl.injuries",
            columns=_INJURY_COLUMNS,
            conflict=("gsis_id", "season", "week", "game_type"),
            connection_url=connection_url,
            empty_message="no injuries to ingest",
            delete_absent_for_season=season,
        )


if __name__ == "__main__":
    main()
