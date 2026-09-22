"""Create nfl.depth_charts.

Week-level published depth charts from nflverse load_depth_charts(seasons).
Grain is (gsis_id, season, week, game_type, position). No intra-week
timestamp: (season, week) is treated as the pre-kickoff chart.
No raw jsonb: nflverse parquet is typed.

Revision ID: 0008_nfl_depth_charts
Revises: 0007_nfl_injuries
Create Date: 2026-09-22

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_nfl_depth_charts"
down_revision: str | None = "0007_nfl_injuries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE TABLE nfl.depth_charts (
    season              int         NOT NULL,
    week                int         NOT NULL,
    game_type           text        NOT NULL,
    team                text        NOT NULL REFERENCES nfl.teams (team_abbr),
    gsis_id             text        NOT NULL REFERENCES nfl.players (gsis_id),
    position            text        NOT NULL,
    depth_position      text,
    depth_team          int,
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gsis_id, season, week, game_type, position)
);

COMMENT ON TABLE nfl.depth_charts IS
    'Weekly published chart, no intra-week timestamp; (season, week) is treated as the pre-kickoff chart.';
COMMENT ON COLUMN nfl.depth_charts.gsis_id IS
    'NFL GSIS ID. Join key to nfl.players.';
COMMENT ON COLUMN nfl.depth_charts.team IS
    'Team on the chart for that week, not current roster latest_team.';
COMMENT ON COLUMN nfl.depth_charts.position IS
    'Roster position on the chart (PK slot). Distinct from depth_position.';
COMMENT ON COLUMN nfl.depth_charts.depth_position IS
    'nflverse formation slot, if present.';
COMMENT ON COLUMN nfl.depth_charts.depth_team IS
    '1 = starter. Null is unknown, not a starter.';

CREATE INDEX ON nfl.depth_charts (gsis_id);
CREATE INDEX ON nfl.depth_charts (team, season, week);
CREATE INDEX ON nfl.depth_charts (season, week);
"""

DOWNGRADE_SQL = """
DROP TABLE nfl.depth_charts;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
