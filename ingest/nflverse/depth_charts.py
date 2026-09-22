"""Load current-season nflverse depth charts into nfl.depth_charts."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings
from ingest.nflverse.write import upsert_frame

_DEPTH_CHART_COLUMNS = (
    "season",
    "week",
    "game_type",
    "team",
    "gsis_id",
    "position",
    "depth_position",
    "depth_team",
    "ingested_at",
)


def _first_present(frame: pl.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _optional_str(frame: pl.DataFrame, name: str) -> pl.Expr:
    if name in frame.columns:
        return pl.col(name).cast(pl.String, strict=False)
    return pl.lit(None).cast(pl.String).alias(name)


def _optional_int(frame: pl.DataFrame, name: str) -> pl.Expr:
    if name in frame.columns:
        return pl.col(name).cast(pl.Int64, strict=False)
    return pl.lit(None).cast(pl.Int64).alias(name)


def _game_type_expr(frame: pl.DataFrame) -> pl.Expr:
    if "game_type" not in frame.columns:
        return pl.lit("REG").alias("game_type")
    game_type = pl.col("game_type").cast(pl.String)
    missing = game_type.is_null() | (game_type == "")
    return pl.when(missing).then(pl.lit("REG")).otherwise(game_type).alias("game_type")


def _resolved_seasons() -> tuple[int, ...]:
    current_season = int(nfl.get_current_season())
    try:
        seasons_mod = importlib.import_module("ingest.nflverse.seasons")
    except ImportError:
        return (current_season,)
    from_env = getattr(seasons_mod, "seasons_from_env", None)
    if not callable(from_env):
        return (current_season,)
    return tuple(
        int(season) for season in from_env(os.environ, current_season=current_season)
    )


def prepare_depth_charts(
    frame: pl.DataFrame,
    *,
    ingested_at: datetime,
    season: int,
) -> pl.DataFrame:
    """Map an nflverse depth-charts frame onto ``nfl.depth_charts``.

    Use ``load_depth_charts(season)``. Pass ``season`` here so historical
    weeks cannot leak in.

    ``ingested_at`` is supplied by the caller; this function does not read the
    clock. Rows without ``gsis_id`` cannot be keyed and are omitted.
    These are weekly published charts, not timestamped snapshots.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)

    if "gsis_id" not in frame.columns:
        raise ValueError("depth charts require gsis_id")
    team_src = _first_present(frame, "team", "club_code")
    if team_src is None:
        raise ValueError("depth charts require team or club_code")
    position_src = _first_present(frame, "position", "pos_abb")
    if position_src is None:
        raise ValueError("depth charts require position or pos_abb")

    return (
        frame.filter(pl.col("season") == season)
        .with_columns(
            pl.col("gsis_id").cast(pl.String),
            pl.col(team_src).alias("team"),
            pl.col(position_src).alias("position"),
            _game_type_expr(frame),
            _optional_str(frame, "depth_position"),
            _optional_int(frame, "depth_team"),
            pl.lit(captured).alias("ingested_at"),
        )
        .filter(pl.col("gsis_id").is_not_null() & (pl.col("gsis_id") != ""))
        .select(*_DEPTH_CHART_COLUMNS)
    )


def main() -> None:
    ingested_at = datetime.now(UTC)
    for season in _resolved_seasons():
        charts = prepare_depth_charts(
            nfl.load_depth_charts(season),
            ingested_at=ingested_at,
            season=season,
        )
        upsert_frame(
            charts,
            table="nfl.depth_charts",
            columns=_DEPTH_CHART_COLUMNS,
            conflict=("gsis_id", "season", "week", "game_type", "position"),
            connection_url=get_settings().postgres_url,
            empty_message="no depth charts to ingest",
        )


if __name__ == "__main__":
    main()
