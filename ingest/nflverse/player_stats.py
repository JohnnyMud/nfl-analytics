"""Load current-season weekly nflverse player stats into nfl.player_stats."""

from __future__ import annotations

from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings
from ingest.nflverse.write import upsert_frame

# Order matches nfl.player_stats / PlayerStat. nflverse `player_id` is renamed
# to `gsis_id` before this select.
_STAT_COLUMNS = (
    "gsis_id",
    "player_name",
    "player_display_name",
    "position",
    "position_group",
    "headshot_url",
    "season",
    "week",
    "season_type",
    "game_id",
    "team",
    "opponent_team",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "sack_yards_lost",
    "sack_fumbles",
    "sack_fumbles_lost",
    "passing_air_yards",
    "passing_yards_after_catch",
    "passing_first_downs",
    "passing_epa",
    "passing_cpoe",
    "passing_2pt_conversions",
    "pacr",
    "passing_10",
    "passing_16",
    "passing_20",
    "passing_40",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_fumbles",
    "rushing_fumbles_lost",
    "rushing_first_downs",
    "rushing_epa",
    "rushing_2pt_conversions",
    "rushing_10",
    "rushing_12",
    "rushing_20",
    "rushing_40",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_fumbles",
    "receiving_fumbles_lost",
    "receiving_air_yards",
    "receiving_yards_after_catch",
    "receiving_first_downs",
    "receiving_epa",
    "receiving_2pt_conversions",
    "receiving_10",
    "receiving_16",
    "receiving_20",
    "receiving_40",
    "racr",
    "target_share",
    "air_yards_share",
    "wopr",
    "special_teams_tds",
    "def_tackles_solo",
    "def_tackles_with_assist",
    "def_tackle_assists",
    "def_tackles_for_loss",
    "def_tackles_for_loss_yards",
    "def_fumbles_forced",
    "def_sacks",
    "def_sack_yards",
    "def_qb_hits",
    "def_interceptions",
    "def_interception_yards",
    "def_pass_defended",
    "def_tds",
    "def_fumbles",
    "def_safeties",
    "def_punt_blocks",
    "def_pat_blocks",
    "def_fg_blocks",
    "def_2pt_atts",
    "def_2pt_made",
    "misc_yards",
    "fumble_recovery_own",
    "fumble_recovery_yards_own",
    "fumble_recovery_opp",
    "fumble_recovery_yards_opp",
    "fumble_recovery_tds",
    "penalties",
    "penalty_yards",
    "fumbles_forced_by_opp",
    "fumbles_not_forced",
    "fumbles_out_of_bounds",
    "fumbles_total",
    "fumbles_lost_total",
    "punt_returns",
    "punt_return_yards",
    "kickoff_returns",
    "kickoff_return_yards",
    "fg_made",
    "fg_att",
    "fg_missed",
    "fg_blocked",
    "fg_long",
    "fg_pct",
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
    "fg_made_50_59",
    "fg_made_60_",
    "fg_missed_0_19",
    "fg_missed_20_29",
    "fg_missed_30_39",
    "fg_missed_40_49",
    "fg_missed_50_59",
    "fg_missed_60_",
    "fg_made_list",
    "fg_missed_list",
    "fg_blocked_list",
    "fg_made_distance",
    "fg_missed_distance",
    "fg_blocked_distance",
    "pat_made",
    "pat_att",
    "pat_missed",
    "pat_blocked",
    "pat_pct",
    "gwfg_made",
    "gwfg_att",
    "gwfg_missed",
    "gwfg_blocked",
    "gwfg_distance",
    "pt_att",
    "pt_blocked",
    "pt_long",
    "pt_yards",
    "pt_inside_20",
    "pt_out_of_bounds",
    "pt_downed",
    "pt_touchback",
    "pt_fair_caught",
    "pt_returned",
    "pt_return_yards",
    "pt_return_tds",
    "pt_net_yards",
    "fantasy_points",
    "fantasy_points_ppr",
    "ingested_at",
)


def prepare_player_stats(
    frame: pl.DataFrame,
    *,
    ingested_at: datetime,
    season: int,
) -> pl.DataFrame:
    """Map weekly nflverse player stats onto ``nfl.player_stats``.

    Use ``load_player_stats(season)`` (default ``summary_level="week"``).
    ``load_player_stats()`` with ``seasons=True`` is every season; pass
    ``season`` here so historical weeks cannot leak in.

    ``ingested_at`` is supplied by the caller; this function does not read the
    clock. Rows without ``player_id`` cannot be keyed and are omitted.
    These are post-game box scores, not point-in-time features.
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)
    return (
        frame.filter(pl.col("season") == season)
        .rename({"player_id": "gsis_id"})
        .with_columns(pl.col("gsis_id").cast(pl.String))
        .filter(pl.col("gsis_id").is_not_null() & (pl.col("gsis_id") != ""))
        .with_columns(pl.lit(captured).alias("ingested_at"))
        .select(*_STAT_COLUMNS)
    )


def main() -> None:
    ingested_at = datetime.now(UTC)
    season = nfl.get_current_season()
    stats = prepare_player_stats(
        nfl.load_player_stats(season),
        ingested_at=ingested_at,
        season=season,
    )
    upsert_frame(
        stats,
        table="nfl.player_stats",
        columns=_STAT_COLUMNS,
        conflict=("gsis_id", "game_id"),
        connection_url=get_settings().postgres_url,
        empty_message="no player stats to ingest",
    )


if __name__ == "__main__":
    main()
