"""Load nflverse depth charts into nfl.depth_charts.

Nightly writes the current season. Set NFLVERSE_SEASON_START/END to backfill
a range; each season is prepared and upserted separately. Absent keys are
not deleted: from 2025 each publication is a new ``snapshot_at``, and a
missing row is unknown, not a retraction.

``snapshot_at`` is the source ``dt`` when the file has one (2025 onward).
Week-only files have no publication time. Those rows use the club's kickoff
for that season, week, and game type, then the earliest kickoff in that
week, then a derived instant for the two labels that are not on the
schedule: SBBYE is the Super Bowl kickoff minus 7 days, and a
regular-season week with no games is the last regular-season kickoff plus
7 days. Those derived instants are not publication times.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings
from ingest.nflverse.schedules import prepare_schedules
from ingest.nflverse.seasons import seasons_from_env
from ingest.nflverse.write import upsert_frame

_DEPTH_COLUMNS = (
    "snapshot_at",
    "team",
    "gsis_id",
    "position",
    "depth_rank",
    "ingested_at",
)

# Slim schedule used only to place week-only charts. Kickoffs are UTC.
_GAME_COLUMNS = (
    "season",
    "week",
    "game_type",
    "home_team",
    "away_team",
    "kickoff_at",
)

_TIMESTAMPED_COLUMNS = ("dt", "team", "gsis_id", "pos_abb", "pos_rank")
_WEEKLY_COLUMNS = (
    "season",
    "club_code",
    "week",
    "game_type",
    "depth_team",
    "gsis_id",
    "depth_position",
)


def prepare_depth_charts(
    frame: pl.DataFrame,
    *,
    ingested_at: datetime,
    season: int,
    games: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Map one season of ``load_depth_charts(season)`` onto ``nfl.depth_charts``.

    ``ingested_at`` is supplied by the caller; this function does not read
    the clock. Rows without ``gsis_id``, team, or a chart slot cannot be
    keyed and are omitted. A week file that lists two ranks for one slot
    keeps the lower rank. ``games`` is required for week-only files and
    ignored when the file carries ``dt``.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)
    if _is_timestamped(frame):
        prepared = _prepare_timestamped(frame, season=season)
    else:
        prepared = _prepare_weekly(frame, season=season, games=games)
    return prepared.with_columns(pl.lit(captured).alias("ingested_at")).select(
        *_DEPTH_COLUMNS
    )


def main() -> None:
    ingested_at = datetime.now(UTC)
    current_season = int(nfl.get_current_season())
    connection_url = get_settings().postgres_url
    for season in seasons_from_env(os.environ, current_season=current_season):
        raw = nfl.load_depth_charts(season)
        games = None
        if not _is_timestamped(raw):
            games = prepare_schedules(
                nfl.load_schedules(season),
                ingested_at=ingested_at,
                season=season,
            ).select(*_GAME_COLUMNS)
        charts = prepare_depth_charts(
            raw,
            ingested_at=ingested_at,
            season=season,
            games=games,
        )
        upsert_frame(
            charts,
            table="nfl.depth_charts",
            columns=_DEPTH_COLUMNS,
            conflict=("gsis_id", "team", "snapshot_at", "position"),
            connection_url=connection_url,
            empty_message="no depth charts to ingest",
        )


def _is_timestamped(frame: pl.DataFrame) -> bool:
    """2025+ releases carry a publication ``dt`` and ``pos_abb`` slot."""
    return "dt" in frame.columns and "pos_abb" in frame.columns


def _prepare_timestamped(frame: pl.DataFrame, *, season: int) -> pl.DataFrame:
    _require_columns(frame, _TIMESTAMPED_COLUMNS, "depth charts")
    scoped = frame
    if "season" in frame.columns:
        scoped = frame.filter(pl.col("season") == season)
    keyed = _drop_unkeyed(
        scoped.with_columns(
            pl.col("team").cast(pl.String),
            pl.col("gsis_id").cast(pl.String),
            pl.col("pos_abb").cast(pl.String).alias("position"),
            pl.col("pos_rank").cast(pl.Int32, strict=False).alias("depth_rank"),
            pl.col("dt").cast(pl.String),
        )
    )
    missing_dt = keyed.filter(pl.col("dt").is_null() | (pl.col("dt") == ""))
    if missing_dt.height:
        raise ValueError("timestamped depth charts include rows without dt")
    stamped = keyed.with_columns(
        pl.col("dt")
        .str.to_datetime(time_zone="UTC")
        .dt.convert_time_zone("UTC")
        .alias("snapshot_at")
    )
    return _collapse(stamped)


def _prepare_weekly(
    frame: pl.DataFrame,
    *,
    season: int,
    games: pl.DataFrame | None,
) -> pl.DataFrame:
    _require_columns(frame, _WEEKLY_COLUMNS, "depth charts")
    if games is None:
        raise ValueError("week-only depth charts need games to place snapshot_at")
    _require_columns(games, _GAME_COLUMNS, "games")
    keyed = _drop_unkeyed(
        frame.filter(pl.col("season") == season).with_columns(
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("game_type").cast(pl.String),
            pl.col("club_code").cast(pl.String).alias("team"),
            pl.col("gsis_id").cast(pl.String),
            pl.col("depth_position").cast(pl.String).alias("position"),
            pl.col("depth_team").cast(pl.Int32, strict=False).alias("depth_rank"),
        )
    )
    placed = _with_weekly_snapshot(keyed, games, season=season)
    missing = placed.filter(pl.col("snapshot_at").is_null())
    if missing.height:
        labels = (
            missing.select("game_type", "week")
            .unique()
            .sort("game_type", "week")
            .head(8)
            .iter_rows()
        )
        rendered = ", ".join(f"{game_type} week {week}" for game_type, week in labels)
        raise ValueError(f"depth chart rows have no snapshot_at for {rendered}")
    return _collapse(placed)


def _with_weekly_snapshot(
    charts: pl.DataFrame,
    games: pl.DataFrame,
    *,
    season: int,
) -> pl.DataFrame:
    """Attach the migration's kickoff fallback as ``snapshot_at``."""
    played = games.filter(pl.col("season") == season).with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("game_type").cast(pl.String),
        pl.col("home_team").cast(pl.String),
        pl.col("away_team").cast(pl.String),
        pl.col("kickoff_at").cast(pl.Datetime(time_zone="UTC")),
    )
    played = played.filter(pl.col("kickoff_at").is_not_null())
    club = (
        pl.concat(
            [
                played.select(
                    "season",
                    "week",
                    "game_type",
                    pl.col("home_team").alias("team"),
                    "kickoff_at",
                ),
                played.select(
                    "season",
                    "week",
                    "game_type",
                    pl.col("away_team").alias("team"),
                    "kickoff_at",
                ),
            ]
        )
        .group_by("season", "week", "game_type", "team")
        .agg(pl.col("kickoff_at").min().alias("club_kickoff"))
    )
    week_earliest = played.group_by("season", "week", "game_type").agg(
        pl.col("kickoff_at").min().alias("week_kickoff")
    )
    joined = charts.join(
        club, on=["season", "week", "game_type", "team"], how="left"
    ).join(week_earliest, on=["season", "week", "game_type"], how="left")
    placed = pl.coalesce("club_kickoff", "week_kickoff")
    sb_anchor = _offset_kickoff(played, game_type="SB", days=-7)
    if sb_anchor is not None:
        placed = (
            pl.when(pl.col("game_type") == "SBBYE")
            .then(_utc_lit(sb_anchor))
            .otherwise(placed)
        )
    extra_reg = _offset_kickoff(played, game_type="REG", days=7, latest=True)
    if extra_reg is not None:
        placed = (
            pl.when(
                (pl.col("game_type") == "REG")
                & pl.col("club_kickoff").is_null()
                & pl.col("week_kickoff").is_null()
            )
            .then(_utc_lit(extra_reg))
            .otherwise(placed)
        )
    return joined.with_columns(placed.alias("snapshot_at"))


def _offset_kickoff(
    played: pl.DataFrame,
    *,
    game_type: str,
    days: int,
    latest: bool = False,
) -> datetime | None:
    kicks = played.filter(pl.col("game_type") == game_type)
    if kicks.is_empty():
        return None
    kickoff = kicks["kickoff_at"].max() if latest else kicks["kickoff_at"].min()
    if not isinstance(kickoff, datetime):
        return None
    if kickoff.tzinfo is None:
        raise ValueError("kickoff_at must be timezone-aware")
    return kickoff.astimezone(UTC) + timedelta(days=days)


def _utc_lit(value: datetime) -> pl.Expr:
    return pl.lit(value.astimezone(UTC)).cast(pl.Datetime(time_zone="UTC"))


def _collapse(frame: pl.DataFrame) -> pl.DataFrame:
    """One row per key. Two ranks for one slot keep the lower rank."""
    return (
        frame.group_by("gsis_id", "team", "snapshot_at", "position")
        .agg(pl.col("depth_rank").min())
        .select("snapshot_at", "team", "gsis_id", "position", "depth_rank")
    )


def _drop_unkeyed(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(
        pl.col("gsis_id").is_not_null()
        & (pl.col("gsis_id") != "")
        & pl.col("team").is_not_null()
        & (pl.col("team") != "")
        & pl.col("position").is_not_null()
        & (pl.col("position") != "")
    )


def _require_columns(
    frame: pl.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


if __name__ == "__main__":
    main()
