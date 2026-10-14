"""Allow predictions before the outcome exists; index player lookups.

A prediction for a game that has not been played has no label. Storing it
with ``y_true`` null keeps predictions and outcomes separate: the label is
attached by the scoring run once the box score is final, never invented.

Downgrade restores ``NOT NULL`` and fails loudly if any unscored prediction
rows exist. It does not delete them.

Revision ID: 0011_prediction_y_true_nullable
Revises: 0010_depth_chart_snapshots
Create Date: 2026-10-14

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_prediction_y_true_nullable"
down_revision: str | None = "0010_depth_chart_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
ALTER TABLE model.prediction ALTER COLUMN y_true DROP NOT NULL;

COMMENT ON COLUMN model.prediction.y_true IS
    'rushing_yards after the game is final. Null means the game had not been played when the row was written. Label only; not a feature.';

CREATE INDEX prediction_gsis_id_game_id_idx ON model.prediction (gsis_id, game_id);
"""

DOWNGRADE_SQL = """
DROP INDEX model.prediction_gsis_id_game_id_idx;

COMMENT ON COLUMN model.prediction.y_true IS
    'rushing_yards after the game is final. Label only; not a feature.';

ALTER TABLE model.prediction ALTER COLUMN y_true SET NOT NULL;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
