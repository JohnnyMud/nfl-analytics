"""Load nflverse rosters into nfl.players.

Nightly (no season-range env) writes the current-season roster and drops
CUT / RET. A multi-season backfill also upserts directory rows for every
``gsis_id`` referenced by that season's weekly stats or injuries so fact-table
FKs succeed. ``latest_team`` / ``status`` on those directory rows are
current-as-of-directory, not historical features.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings
from ingest.nflverse.seasons import seasons_from_env
from ingest.nflverse.write import upsert_frame

# Released / retired rows stay on the seasonal roster file; they are not
# currently on a club. Practice squad (DEV), reserve lists, and exempt stay.
_INACTIVE_STATUSES = ("CUT", "RET")

# Order matches nfl.players / prepare_players output. No raw column
# (see migration 0005_drop_nfl_raw).
_PLAYER_COLUMNS = (
    "gsis_id",
    "display_name",
    "common_first_name",
    "first_name",
    "last_name",
    "short_name",
    "football_name",
    "suffix",
    "esb_id",
    "nfl_id",
    "pfr_id",
    "pff_id",
    "otc_id",
    "espn_id",
    "smart_id",
    "birth_date",
    "position_group",
    "position",
    "ngs_position_group",
    "ngs_position",
    "height",
    "weight",
    "headshot",
    "college_name",
    "college_conference",
    "jersey_number",
    "rookie_season",
    "last_season",
    "latest_team",
    "status",
    "ngs_status",
    "ngs_status_short_description",
    "years_of_experience",
    "pff_position",
    "pff_status",
    "draft_year",
    "draft_round",
    "draft_pick",
    "draft_team",
    "ingested_at",
)


def prepare_players(
    rosters: pl.DataFrame,
    directory: pl.DataFrame,
    *,
    ingested_at: datetime,
) -> pl.DataFrame:
    """Map a seasonal roster onto ``nfl.players``.

    Use ``load_rosters(season)`` for who is on a club this year, then
    ``load_players()`` only as an ID/draft directory. ``load_players()`` is a
    career table (one row per person ever tracked), not a season roster.

    ``ingested_at`` is supplied by the caller; this function does not read the
    clock. Rows without ``gsis_id`` cannot be keyed and are omitted.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)

    current = rosters.with_columns(pl.col("gsis_id").cast(pl.String)).filter(
        pl.col("gsis_id").is_not_null() & (pl.col("gsis_id") != ""),
        ~pl.col("status").is_in(_INACTIVE_STATUSES),
    )
    joined = current.join(directory, on="gsis_id", how="left", suffix="_dir")
    return joined.select(
        pl.col("gsis_id"),
        pl.coalesce("display_name", "full_name").alias("display_name"),
        pl.col("common_first_name"),
        pl.coalesce("first_name_dir", "first_name").alias("first_name"),
        pl.coalesce("last_name_dir", "last_name").alias("last_name"),
        pl.col("short_name"),
        pl.coalesce("football_name_dir", "football_name").alias("football_name"),
        pl.col("suffix"),
        pl.coalesce("esb_id_dir", "esb_id").alias("esb_id"),
        pl.col("nfl_id"),
        pl.coalesce("pfr_id_dir", "pfr_id").alias("pfr_id"),
        pl.coalesce("pff_id_dir", "pff_id").alias("pff_id"),
        pl.col("otc_id"),
        pl.coalesce("espn_id_dir", "espn_id").alias("espn_id"),
        pl.coalesce("smart_id_dir", "smart_id").alias("smart_id"),
        pl.coalesce(
            pl.col("birth_date_dir").cast(pl.String).str.to_date("%Y-%m-%d"),
            pl.col("birth_date"),
        ).alias("birth_date"),
        pl.col("position_group"),
        pl.coalesce("position", "position_dir").alias("position"),
        pl.col("ngs_position_group"),
        pl.coalesce("ngs_position", "ngs_position_dir").alias("ngs_position"),
        pl.coalesce("height", "height_dir").alias("height"),
        pl.coalesce("weight", "weight_dir").alias("weight"),
        pl.coalesce("headshot", "headshot_url").alias("headshot"),
        pl.coalesce("college_name", "college").alias("college_name"),
        pl.col("college_conference"),
        pl.coalesce(
            pl.col("jersey_number").cast(pl.String),
            pl.col("jersey_number_dir").cast(pl.String),
        ).alias("jersey_number"),
        pl.coalesce("rookie_season", "rookie_year").alias("rookie_season"),
        pl.col("season").alias("last_season"),
        pl.col("team").alias("latest_team"),
        pl.col("status"),
        pl.col("ngs_status"),
        pl.coalesce("ngs_status_short_description", "status_description_abbr").alias(
            "ngs_status_short_description"
        ),
        pl.coalesce("years_of_experience", "years_exp").alias("years_of_experience"),
        pl.col("pff_position"),
        pl.col("pff_status"),
        pl.col("draft_year"),
        pl.col("draft_round"),
        pl.coalesce("draft_pick", "draft_number").alias("draft_pick"),
        pl.col("draft_team"),
        pl.lit(captured).alias("ingested_at"),
    ).select(*_PLAYER_COLUMNS)


def prepare_referenced_players(
    directory: pl.DataFrame,
    referenced_ids: Sequence[str],
    *,
    ingested_at: datetime,
) -> pl.DataFrame:
    """Map ``load_players()`` directory rows onto ``nfl.players`` for FK targets.

    Used so weekly stats and injuries can reference a ``gsis_id`` that is not
    on the current roster (CUT / RET / career-only). Does not drop inactive
    statuses. Ids absent from ``referenced_ids`` or from the directory are
    omitted. ``ingested_at`` is supplied by the caller; this function does
    not read the clock.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)
    wanted = [gsis_id for gsis_id in referenced_ids if gsis_id]
    id_match = pl.col("gsis_id").is_in(wanted) if wanted else pl.lit(False)
    return (
        directory.with_columns(pl.col("gsis_id").cast(pl.String))
        .filter(
            pl.col("gsis_id").is_not_null() & (pl.col("gsis_id") != ""),
            id_match,
        )
        .with_columns(
            pl.col("birth_date").cast(pl.String).str.to_date("%Y-%m-%d"),
            pl.col("jersey_number").cast(pl.String),
            pl.lit(captured).alias("ingested_at"),
        )
        .select(*_PLAYER_COLUMNS)
    )


def referenced_gsis_ids(
    stats: pl.DataFrame,
    injuries: pl.DataFrame,
) -> tuple[str, ...]:
    """Unique ``gsis_id`` values from weekly stats (``player_id``) and injuries."""
    return tuple(
        dict.fromkeys(
            (
                *_string_ids(stats, "player_id"),
                *_string_ids(injuries, "gsis_id"),
            )
        )
    )


def _string_ids(frame: pl.DataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        raise ValueError(f"frame missing {column!r}")
    values = (
        frame.select(pl.col(column).cast(pl.String).alias("gsis_id"))
        .filter(pl.col("gsis_id").is_not_null() & (pl.col("gsis_id") != ""))
        .get_column("gsis_id")
        .to_list()
    )
    return [str(value) for value in values]


def main() -> None:
    ingested_at = datetime.now(UTC)
    current_season = int(nfl.get_current_season())
    seasons = seasons_from_env(os.environ, current_season=current_season)
    directory = nfl.load_players()
    connection_url = get_settings().postgres_url
    include_referenced = seasons != (current_season,)

    for season in seasons:
        players = prepare_players(
            nfl.load_rosters(season),
            directory,
            ingested_at=ingested_at,
        )
        upsert_frame(
            players,
            table="nfl.players",
            columns=_PLAYER_COLUMNS,
            conflict=("gsis_id",),
            connection_url=connection_url,
            empty_message="no players to ingest",
        )
        if not include_referenced:
            continue
        referenced = prepare_referenced_players(
            directory,
            referenced_gsis_ids(
                nfl.load_player_stats(season),
                nfl.load_injuries(season),
            ),
            ingested_at=ingested_at,
        )
        if referenced.is_empty():
            continue
        upsert_frame(
            referenced,
            table="nfl.players",
            columns=_PLAYER_COLUMNS,
            conflict=("gsis_id",),
            connection_url=connection_url,
            empty_message="no referenced players to ingest",
        )


if __name__ == "__main__":
    main()
