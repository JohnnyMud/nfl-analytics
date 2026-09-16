"""Load 2026-season nflverse rosters into nfl.players."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.env import load_dotenv

# Released / retired rows stay on the seasonal roster file; they are not
# currently on a club. Practice squad (DEV), reserve lists, and exempt stay.
_INACTIVE_STATUSES = ("CUT", "RET")


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
    )


def _adbc_database_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    return url


def main() -> None:
    ingested_at = datetime.now(UTC)
    season = nfl.get_current_season()
    players = prepare_players(
        nfl.load_rosters(season),
        nfl.load_players(),
        ingested_at=ingested_at,
    )
    players.write_database(
        table_name="nfl.players",
        connection=_adbc_database_url(),
        engine="adbc",
        if_table_exists="append",
    )


if __name__ == "__main__":
    main()
