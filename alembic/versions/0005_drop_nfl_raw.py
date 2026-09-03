"""Drop raw jsonb from nfl dimension tables.

nflverse loads are typed parquet copies, not vendor API payloads. raw belongs
on market.odds_observation, not on teams/players/games.

Revision ID: 0005_drop_nfl_raw
Revises: 0004_nfl_dimension_tables
Create Date: 2026-09-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_drop_nfl_raw"
down_revision: str | None = "0004_nfl_dimension_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
ALTER TABLE nfl.teams DROP COLUMN raw;
ALTER TABLE nfl.players DROP COLUMN raw;
ALTER TABLE nfl.games DROP COLUMN raw;
"""

DOWNGRADE_SQL = """
ALTER TABLE nfl.teams ADD COLUMN raw jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE nfl.players ADD COLUMN raw jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE nfl.games ADD COLUMN raw jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE nfl.teams ALTER COLUMN raw DROP DEFAULT;
ALTER TABLE nfl.players ALTER COLUMN raw DROP DEFAULT;
ALTER TABLE nfl.games ALTER COLUMN raw DROP DEFAULT;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
