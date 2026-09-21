"""Create nfl.injuries.

Week-level injury and practice reports from nflverse load_injuries(seasons).
Grain is (gsis_id, season, week, game_type). No game_id and no report
timestamp: this is the published weekly report, not a point-in-time log.
No raw jsonb: nflverse parquet is typed.

Revision ID: 0007_nfl_injuries
Revises: 0006_nfl_player_stats
Create Date: 2026-09-21

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_nfl_injuries"
down_revision: str | None = "0006_nfl_player_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE TABLE nfl.injuries (
    season                      int         NOT NULL,
    season_type                 text        NOT NULL,
    game_type                   text        NOT NULL,
    team                        text        NOT NULL REFERENCES nfl.teams (team_abbr),
    week                        int         NOT NULL,
    gsis_id                     text        NOT NULL REFERENCES nfl.players (gsis_id),
    position                    text,
    full_name                   text,
    first_name                  text,
    last_name                   text,
    report_primary_injury       text,
    report_secondary_injury     text,
    report_status               text,
    practice_primary_injury     text,
    practice_secondary_injury   text,
    practice_status             text,
    ingested_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gsis_id, season, week, game_type)
);

COMMENT ON TABLE nfl.injuries IS
    'Weekly injury/practice reports keyed by gsis_id + season + week + game_type. No report timestamp; not a point-in-time log.';
COMMENT ON COLUMN nfl.injuries.gsis_id IS
    'NFL GSIS ID. Join key to nfl.players.';
COMMENT ON COLUMN nfl.injuries.team IS
    'Team on the report for that week, not current roster latest_team.';
COMMENT ON COLUMN nfl.injuries.report_status IS
    'Game-status designation (Out/Doubtful/Questionable). Null when only a practice report exists.';
COMMENT ON COLUMN nfl.injuries.practice_status IS
    'Practice participation for that week. Null is unknown, not full participation.';

CREATE INDEX ON nfl.injuries (gsis_id);
CREATE INDEX ON nfl.injuries (team, season, week);
CREATE INDEX ON nfl.injuries (season, week);
"""

DOWNGRADE_SQL = """
DROP TABLE nfl.injuries;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
