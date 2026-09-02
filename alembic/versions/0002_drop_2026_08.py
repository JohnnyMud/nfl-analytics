"""Drop the unused 2026-08 odds_observation partition.

Capture never started in August, and live inserts cannot land there now.
Foreign keys onto the parent table block DROP PARTITION, so detach first.

Revision ID: 0002_drop_2026_08
Revises: 0001_odds_capture
Create Date: 2026-09-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_drop_2026_08"
down_revision: str | None = "0001_odds_capture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
ALTER TABLE odds_observation DETACH PARTITION odds_observation_2026_08;
DROP TABLE odds_observation_2026_08;
"""

DOWNGRADE_SQL = """
CREATE TABLE odds_observation_2026_08 PARTITION OF odds_observation
    FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00');
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
