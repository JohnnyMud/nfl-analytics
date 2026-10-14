"""Replace week-grain depth charts with snapshot rows.

Identity is player + team + snapshot_at + position. A player can hold
more than one chart position at the same instant, so position stays in
the key. depth_rank does not: the timestamped source has one rank per
slot, and a week file that lists two ranks for one slot keeps the lower
rank.

snapshot_at is the source ``dt`` when the file has one. Week-only files
have no publication time. Those rows use the club's kickoff for that
season/week/game_type, then the earliest kickoff in that week, then a
derived instant for the two week labels that are not on the schedule
(SBBYE, and the extra regular-season week after the last played week).

Revision ID: 0010_depth_chart_snapshots
Revises: 0009_rush_rb_predictions
Create Date: 2026-09-22

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_depth_chart_snapshots"
down_revision: str | None = "0009_rush_rb_predictions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
DROP TABLE nfl.depth_charts;

CREATE TABLE nfl.depth_charts (
    snapshot_at   timestamptz NOT NULL,
    team          text        NOT NULL REFERENCES nfl.teams (team_abbr),
    gsis_id       text        NOT NULL REFERENCES nfl.players (gsis_id),
    position      text        NOT NULL,
    depth_rank    int,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gsis_id, team, snapshot_at, position)
);

COMMENT ON TABLE nfl.depth_charts IS
    'Depth-chart slots keyed by player, team, snapshot_at, and position. Season and week are not part of the identity.';
COMMENT ON COLUMN nfl.depth_charts.snapshot_at IS
    'Temporal anchor, UTC. Observed files store source dt. Week-only files store the club kickoff, else that week''s earliest kickoff. SBBYE is the Super Bowl kickoff minus 7 days. A regular-season week with no games is the last regular-season kickoff plus 7 days. Those derived instants are not publication times.';
COMMENT ON COLUMN nfl.depth_charts.team IS
    'Club on the chart at snapshot_at, not current roster latest_team.';
COMMENT ON COLUMN nfl.depth_charts.gsis_id IS
    'NFL GSIS ID. Join key to nfl.players.';
COMMENT ON COLUMN nfl.depth_charts.position IS
    'Chart slot at this snapshot (depth_position or pos_abb). Distinct from roster position. A player may have several.';
COMMENT ON COLUMN nfl.depth_charts.depth_rank IS
    '1 = starter. Not part of the key. Null is unknown, not a starter. A week file that lists two ranks for one slot keeps the lower rank.';

CREATE INDEX ON nfl.depth_charts (gsis_id, snapshot_at);
CREATE INDEX ON nfl.depth_charts (team, snapshot_at);
"""

DOWNGRADE_SQL = """
DROP TABLE nfl.depth_charts;

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
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
