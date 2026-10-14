"""Write and prune stored rush_rb artifacts in ``model.*``.

Every function runs inside the caller's transaction. A run is written in one
transaction, so a failure part-way leaves no rows from that run.

``model.feature_row`` is keyed without ``run_id``: a vector is written once
and shared by every run that scored that player-game. If a rebuilt vector
differs from the stored one (a source row was corrected upstream), the write
raises instead of overwriting, because older runs were scored on the stored
vector. Bump the feature-set version to rebuild.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from features.rush_yards import RushRbV1
from models.rush_yards.payload import features_to_payload
from models.rush_yards.types import MetricRecord, PredictionRecord


class FeatureRowConflict(RuntimeError):
    """A stored feature vector disagrees with the vector rebuilt for this run."""


@dataclass(frozen=True, slots=True)
class RunWriteSummary:
    run_id: UUID
    feature_rows_inserted: int
    feature_rows_already_stored: int
    predictions: int
    metrics: int


def write_run(
    conn: Connection,
    *,
    run_id: UUID,
    features: Sequence[RushRbV1],
    predictions: Sequence[PredictionRecord],
    metrics: Sequence[MetricRecord],
    built_at: datetime,
) -> RunWriteSummary:
    """Persist one run. Raises before writing predictions on any mismatch."""
    if built_at.tzinfo is None or built_at.utcoffset() is None:
        raise ValueError("built_at must be timezone-aware")
    if any(pred.run_id != run_id for pred in predictions):
        raise ValueError("every prediction must carry this run_id")
    if any(metric.run_id != run_id for metric in metrics):
        raise ValueError("every metric must carry this run_id")
    predicted_keys = {(pred.gsis_id, pred.game_id) for pred in predictions}
    feature_keys = {(row.gsis_id, row.game_id) for row in features}
    if predicted_keys != feature_keys:
        raise ValueError("feature rows and predictions must cover the same games")

    inserted, existing = _write_feature_rows(conn, features, built_at=built_at)
    _write_predictions(conn, predictions)
    _write_metrics(conn, metrics)
    return RunWriteSummary(
        run_id=run_id,
        feature_rows_inserted=inserted,
        feature_rows_already_stored=existing,
        predictions=len(predictions),
        metrics=len(metrics),
    )


def _write_feature_rows(
    conn: Connection, features: Sequence[RushRbV1], *, built_at: datetime
) -> tuple[int, int]:
    conn.execute(
        text(
            """
            CREATE TEMP TABLE incoming_feature_row
                (LIKE model.feature_row INCLUDING DEFAULTS)
                ON COMMIT DROP
            """
        )
    )
    if features:
        conn.execute(
            text(
                """
                INSERT INTO incoming_feature_row (
                    feature_set_version, gsis_id, game_id, as_of, payload, built_at
                )
                VALUES (
                    :feature_set_version, :gsis_id, :game_id, :as_of,
                    CAST(:payload AS jsonb), :built_at
                )
                """
            ),
            [
                {
                    "feature_set_version": row.feature_set_version,
                    "gsis_id": row.gsis_id,
                    "game_id": row.game_id,
                    "as_of": row.as_of,
                    "payload": json.dumps(features_to_payload(row)),
                    "built_at": built_at,
                }
                for row in features
            ],
        )
    conflicts = conn.execute(
        text(
            """
            SELECT i.gsis_id, i.game_id
            FROM incoming_feature_row AS i
            JOIN model.feature_row AS f
              USING (feature_set_version, gsis_id, game_id)
            WHERE f.payload <> i.payload OR f.as_of <> i.as_of
            LIMIT 5
            """
        )
    ).all()
    if conflicts:
        sample = ", ".join(f"{row.gsis_id}/{row.game_id}" for row in conflicts)
        raise FeatureRowConflict(
            "rebuilt feature vectors differ from stored rows "
            f"(e.g. {sample}); bump the feature-set version"
        )
    inserted = conn.execute(
        text(
            """
            INSERT INTO model.feature_row
            SELECT * FROM incoming_feature_row
            ON CONFLICT (feature_set_version, gsis_id, game_id) DO NOTHING
            """
        )
    ).rowcount
    conn.execute(text("DROP TABLE incoming_feature_row"))
    return inserted, len(features) - inserted


def _write_predictions(
    conn: Connection, predictions: Sequence[PredictionRecord]
) -> None:
    if not predictions:
        return
    conn.execute(
        text(
            """
            INSERT INTO model.prediction (
                run_id, model_name, model_version, feature_set_version,
                gsis_id, game_id, as_of, y_hat, y_true, predicted_at
            )
            VALUES (
                :run_id, :model_name, :model_version, :feature_set_version,
                :gsis_id, :game_id, :as_of, :y_hat, :y_true, :predicted_at
            )
            """
        ),
        [pred.model_dump(exclude={"season", "week"}) for pred in predictions],
    )


def _write_metrics(conn: Connection, metrics: Sequence[MetricRecord]) -> None:
    if not metrics:
        return
    conn.execute(
        text(
            """
            INSERT INTO model.metric (
                run_id, model_name, season, mae, rmse, n, n_unknown
            )
            VALUES (:run_id, :model_name, :season, :mae, :rmse, :n, :n_unknown)
            """
        ),
        [metric.model_dump() for metric in metrics],
    )


@dataclass(frozen=True, slots=True)
class PruneSummary:
    kept_runs: tuple[UUID, ...]
    deleted_runs: tuple[UUID, ...]
    predictions_deleted: int
    metrics_deleted: int
    feature_rows_deleted: int


def prune_runs(conn: Connection, *, keep: int, dry_run: bool) -> PruneSummary:
    """Delete every run except the newest ``keep`` by ``predicted_at``.

    Feature rows no remaining prediction references are deleted too. Derived
    artifacts only; nothing under ``nfl.*`` or ``market.*`` is touched.
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    runs = [
        row.run_id
        for row in conn.execute(
            text(
                """
                SELECT run_id FROM model.prediction
                GROUP BY run_id
                ORDER BY max(predicted_at) DESC
                """
            )
        )
    ]
    kept = tuple(runs[:keep])
    doomed = tuple(runs[keep:])
    if dry_run or not doomed:
        return PruneSummary(kept, doomed, 0, 0, 0)
    params = {"runs": list(doomed)}
    predictions = conn.execute(
        text("DELETE FROM model.prediction WHERE run_id = ANY(:runs)"), params
    ).rowcount
    metrics = conn.execute(
        text("DELETE FROM model.metric WHERE run_id = ANY(:runs)"), params
    ).rowcount
    feature_rows = conn.execute(
        text(
            """
            DELETE FROM model.feature_row AS f
            WHERE NOT EXISTS (
                SELECT 1 FROM model.prediction AS p
                WHERE p.feature_set_version = f.feature_set_version
                  AND p.gsis_id = f.gsis_id
                  AND p.game_id = f.game_id
            )
            """
        )
    ).rowcount
    return PruneSummary(kept, doomed, predictions, metrics, feature_rows)
