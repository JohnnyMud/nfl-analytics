"""Create nfl.player_stats.

Game-level weekly box scores from nflverse load_player_stats(seasons,
summary_level="week"). Keyed by gsis_id (nflverse player_id) and nflverse
game_id. Not point-in-time features; values exist only after the game is
played. No raw jsonb: nflverse parquet is typed.

Revision ID: 0006_nfl_player_stats
Revises: 0005_drop_nfl_raw
Create Date: 2026-09-15

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_nfl_player_stats"
down_revision: str | None = "0005_drop_nfl_raw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE TABLE nfl.player_stats (
    gsis_id                         text             NOT NULL REFERENCES nfl.players (gsis_id),
    player_name                     text,
    player_display_name             text,
    position                        text,
    position_group                  text,
    headshot_url                    text,
    season                          int              NOT NULL,
    week                            int              NOT NULL,
    season_type                     text             NOT NULL,
    game_id                         text             NOT NULL REFERENCES nfl.games (game_id),
    team                            text             NOT NULL REFERENCES nfl.teams (team_abbr),
    opponent_team                   text             NOT NULL REFERENCES nfl.teams (team_abbr),
    completions                     int,
    attempts                        int,
    passing_yards                   int,
    passing_tds                     int,
    passing_interceptions           int,
    sacks_suffered                  int,
    sack_yards_lost                 int,
    sack_fumbles                    int,
    sack_fumbles_lost               int,
    passing_air_yards               int,
    passing_yards_after_catch       int,
    passing_first_downs             int,
    passing_epa                     double precision,
    passing_cpoe                    double precision,
    passing_2pt_conversions         int,
    pacr                            double precision,
    passing_10                      int,
    passing_16                      int,
    passing_20                      int,
    passing_40                      int,
    carries                         int,
    rushing_yards                   int,
    rushing_tds                     int,
    rushing_fumbles                 int,
    rushing_fumbles_lost            int,
    rushing_first_downs             int,
    rushing_epa                     double precision,
    rushing_2pt_conversions         int,
    rushing_10                      int,
    rushing_12                      int,
    rushing_20                      int,
    rushing_40                      int,
    receptions                      int,
    targets                         int,
    receiving_yards                 int,
    receiving_tds                   int,
    receiving_fumbles               int,
    receiving_fumbles_lost          int,
    receiving_air_yards             int,
    receiving_yards_after_catch     int,
    receiving_first_downs           int,
    receiving_epa                   double precision,
    receiving_2pt_conversions       int,
    receiving_10                    int,
    receiving_16                    int,
    receiving_20                    int,
    receiving_40                    int,
    racr                            double precision,
    target_share                    double precision,
    air_yards_share                 double precision,
    wopr                            double precision,
    special_teams_tds               int,
    def_tackles_solo                int,
    def_tackles_with_assist         int,
    def_tackle_assists              int,
    def_tackles_for_loss            int,
    def_tackles_for_loss_yards      int,
    def_fumbles_forced              int,
    def_sacks                       double precision,
    def_sack_yards                  double precision,
    def_qb_hits                     int,
    def_interceptions               int,
    def_interception_yards          int,
    def_pass_defended               int,
    def_tds                         int,
    def_fumbles                     int,
    def_safeties                    int,
    def_punt_blocks                 int,
    def_pat_blocks                  int,
    def_fg_blocks                   int,
    def_2pt_atts                    int,
    def_2pt_made                    int,
    misc_yards                      int,
    fumble_recovery_own             int,
    fumble_recovery_yards_own       int,
    fumble_recovery_opp             int,
    fumble_recovery_yards_opp       int,
    fumble_recovery_tds             int,
    penalties                       int,
    penalty_yards                   int,
    fumbles_forced_by_opp           int,
    fumbles_not_forced              int,
    fumbles_out_of_bounds           int,
    fumbles_total                   int,
    fumbles_lost_total              int,
    punt_returns                    int,
    punt_return_yards               int,
    kickoff_returns                 int,
    kickoff_return_yards            int,
    fg_made                         int,
    fg_att                          int,
    fg_missed                       int,
    fg_blocked                      int,
    fg_long                         int,
    fg_pct                          double precision,
    fg_made_0_19                    int,
    fg_made_20_29                   int,
    fg_made_30_39                   int,
    fg_made_40_49                   int,
    fg_made_50_59                   int,
    fg_made_60_                     int,
    fg_missed_0_19                  int,
    fg_missed_20_29                 int,
    fg_missed_30_39                 int,
    fg_missed_40_49                 int,
    fg_missed_50_59                 int,
    fg_missed_60_                   int,
    fg_made_list                    text,
    fg_missed_list                  text,
    fg_blocked_list                 text,
    fg_made_distance                int,
    fg_missed_distance              int,
    fg_blocked_distance             int,
    pat_made                        int,
    pat_att                         int,
    pat_missed                      int,
    pat_blocked                     int,
    pat_pct                         double precision,
    gwfg_made                       int,
    gwfg_att                        int,
    gwfg_missed                     int,
    gwfg_blocked                    int,
    gwfg_distance                   int,
    pt_att                          int,
    pt_blocked                      int,
    pt_long                         int,
    pt_yards                        int,
    pt_inside_20                    int,
    pt_out_of_bounds                int,
    pt_downed                       int,
    pt_touchback                    int,
    pt_fair_caught                  int,
    pt_returned                     int,
    pt_return_yards                 int,
    pt_return_tds                   int,
    pt_net_yards                    int,
    fantasy_points                  double precision,
    fantasy_points_ppr              double precision,
    ingested_at                     timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (gsis_id, game_id),
    CHECK (team <> opponent_team)
);

COMMENT ON TABLE nfl.player_stats IS
    'Weekly player box scores keyed by gsis_id + nflverse game_id. Not point-in-time features; values exist only after the game is played.';
COMMENT ON COLUMN nfl.player_stats.gsis_id IS
    'nflverse player_id; join key to nfl.players.';
COMMENT ON COLUMN nfl.player_stats.team IS
    'Team for that game, not current roster latest_team.';
COMMENT ON COLUMN nfl.player_stats.opponent_team IS
    'Opponent for that game, not current roster latest_team.';

CREATE INDEX ON nfl.player_stats (gsis_id);
CREATE INDEX ON nfl.player_stats (game_id);
CREATE INDEX ON nfl.player_stats (season, week);
CREATE INDEX ON nfl.player_stats (team, season);
"""

DOWNGRADE_SQL = """
DROP TABLE nfl.player_stats;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
