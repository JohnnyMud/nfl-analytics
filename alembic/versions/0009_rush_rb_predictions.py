"""Create model schema and rush_rb stored artifacts.

Feature rows, walk-forward predictions, and MAE/RMSE metrics for
rush_rb_v1. A prediction without model version, feature-set version,
as_of, and run_id is not stored.

Revision ID: 0009_rush_rb_predictions
Revises: 0008_nfl_depth_charts
Create Date: 2026-09-22

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_rush_rb_predictions"
down_revision: str | None = "0008_nfl_depth_charts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE SCHEMA IF NOT EXISTS model;

COMMENT ON SCHEMA model IS
    'Stored feature rows, predictions, and metrics. Every prediction carries model version, feature-set version, as_of, and run_id.';

CREATE TABLE model.feature_row (
    feature_set_version text        NOT NULL,
    gsis_id             text        NOT NULL,
    game_id             text        NOT NULL,
    as_of               timestamptz NOT NULL,
    payload             jsonb       NOT NULL,
    built_at            timestamptz NOT NULL,
    PRIMARY KEY (feature_set_version, gsis_id, game_id)
);

COMMENT ON TABLE model.feature_row IS
    'Point-in-time feature vectors. payload maps each registry name to Known or Unknown.';
COMMENT ON COLUMN model.feature_row.as_of IS
    'Kickoff-relative as_of used to build the vector. UTC timestamptz.';
COMMENT ON COLUMN model.feature_row.payload IS
    'Each registry name -> {"kind": "known", "value": ...} or {"kind": "unknown", "reason": "..."}.';
COMMENT ON COLUMN model.feature_row.built_at IS
    'When the vector was materialized. UTC timestamptz. Not a feature as_of.';

CREATE TABLE model.prediction (
    run_id              uuid        NOT NULL,
    model_name          text        NOT NULL,
    model_version       text        NOT NULL,
    feature_set_version text        NOT NULL,
    gsis_id             text        NOT NULL,
    game_id             text        NOT NULL,
    as_of               timestamptz NOT NULL,
    y_hat               double precision,
    y_true              double precision NOT NULL,
    predicted_at        timestamptz NOT NULL,
    PRIMARY KEY (run_id, model_name, gsis_id, game_id)
);

COMMENT ON TABLE model.prediction IS
    'Walk-forward point predictions. y_hat is null iff the predictor returned Unknown (baselines only).';
COMMENT ON COLUMN model.prediction.model_name IS
    'xgboost / lightgbm / baseline_std / baseline_last4.';
COMMENT ON COLUMN model.prediction.y_hat IS
    'Null iff the predictor returned Unknown (baselines only). Never a filled 0.';
COMMENT ON COLUMN model.prediction.y_true IS
    'rushing_yards after the game is final. Label only; not a feature.';
COMMENT ON COLUMN model.prediction.as_of IS
    'Feature as_of (target kickoff_at). UTC timestamptz.';
COMMENT ON COLUMN model.prediction.predicted_at IS
    'When this row was produced. UTC timestamptz.';

CREATE TABLE model.metric (
    run_id      uuid             NOT NULL,
    model_name  text             NOT NULL,
    season      int,
    mae         double precision NOT NULL,
    rmse        double precision NOT NULL,
    n           int              NOT NULL,
    n_unknown   int              NOT NULL
);

CREATE UNIQUE INDEX model_metric_run_model_season_uidx
    ON model.metric (run_id, model_name, COALESCE(season, -1));

COMMENT ON TABLE model.metric IS
    'MAE and RMSE per model. season NULL means overall across scored seasons.';
COMMENT ON COLUMN model.metric.season IS
    'Null means overall. Uniqueness uses COALESCE(season, -1).';
COMMENT ON COLUMN model.metric.n IS
    'Rows included in MAE/RMSE (y_hat is not null).';
COMMENT ON COLUMN model.metric.n_unknown IS
    'Rows excluded because the predictor returned Unknown.';
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS model.metric;
DROP TABLE IF EXISTS model.prediction;
DROP TABLE IF EXISTS model.feature_row;
DROP SCHEMA IF EXISTS model;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
