"""write_run persists a whole run or nothing; stored vectors are never overwritten."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from features.rush_yards import RushRbV1
from features.types import Known
from models.rush_yards.store import FeatureRowConflict, prune_runs, write_run
from models.rush_yards.types import WalkForwardResult
from models.rush_yards.walk_forward import walk_forward
from tests.models.helpers import population

PREDICTED_AT = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)


@pytest.fixture
def model_engine(migrated_engine: Engine) -> Iterator[Engine]:
    yield migrated_engine
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE model.prediction, model.metric, model.feature_row"))


def _run() -> WalkForwardResult:
    return walk_forward(
        population(),
        predicted_at=PREDICTED_AT,
        score_start=2016,
        score_end=2016,
        n_estimators=5,
        run_id=uuid4(),
    )


def _features_for(result: WalkForwardResult) -> list[RushRbV1]:
    scored = {(pred.gsis_id, pred.game_id) for pred in result.predictions}
    return [
        row.features for row in population() if (row.gsis_id, row.game_id) in scored
    ]


def _write(engine: Engine, result: WalkForwardResult) -> None:
    with engine.begin() as conn:
        write_run(
            conn,
            run_id=result.run_id,
            features=_features_for(result),
            predictions=result.predictions,
            metrics=result.metrics,
            built_at=PREDICTED_AT,
        )


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_run_rows_carry_provenance_and_unknown_stays_null(model_engine: Engine) -> None:
    result = _run()
    _write(model_engine, result)

    with model_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT model_name, model_version, feature_set_version, as_of,
                       predicted_at, y_hat, y_true
                FROM model.prediction WHERE run_id = :run_id
                """
            ),
            {"run_id": result.run_id},
        ).all()
        metrics = conn.execute(
            text(
                """
                SELECT model_name, n, n_unknown FROM model.metric
                WHERE run_id = :run_id AND season IS NULL
                """
            ),
            {"run_id": result.run_id},
        ).all()

    assert len(rows) == len(result.predictions)
    assert all(row.model_version and row.feature_set_version for row in rows)
    assert all(row.predicted_at == PREDICTED_AT for row in rows)
    assert any(row.model_name == "baseline_std" and row.y_hat is None for row in rows)
    per_model = {name: sum(r.model_name == name for r in rows) for name, *_ in metrics}
    for name, n, n_unknown in metrics:
        assert n + n_unknown == per_model[name]


def test_rerun_adds_a_run_and_reuses_feature_rows(model_engine: Engine) -> None:
    first, second = _run(), _run()
    _write(model_engine, first)
    feature_rows = _count(model_engine, "model.feature_row")
    _write(model_engine, second)

    assert _count(model_engine, "model.feature_row") == feature_rows
    with model_engine.connect() as conn:
        runs = conn.execute(
            text("SELECT count(DISTINCT run_id) FROM model.prediction")
        ).scalar_one()
    assert runs == 2


def test_changed_vector_raises_and_writes_nothing(model_engine: Engine) -> None:
    _write(model_engine, _run())
    predictions_before = _count(model_engine, "model.prediction")

    second = _run()
    features = _features_for(second)
    features[0] = features[0].model_copy(
        update={"player_last_rush_yards": Known[float](value=-1.0)}
    )
    with pytest.raises(FeatureRowConflict):
        with model_engine.begin() as conn:
            write_run(
                conn,
                run_id=second.run_id,
                features=features,
                predictions=second.predictions,
                metrics=second.metrics,
                built_at=PREDICTED_AT,
            )
    assert _count(model_engine, "model.prediction") == predictions_before


def test_failure_after_feature_rows_rolls_back_the_whole_run(
    model_engine: Engine,
) -> None:
    result = _run()
    duplicated = (*result.predictions, result.predictions[0])
    with pytest.raises(Exception, match="duplicate key"):
        with model_engine.begin() as conn:
            write_run(
                conn,
                run_id=result.run_id,
                features=_features_for(result),
                predictions=duplicated,
                metrics=result.metrics,
                built_at=PREDICTED_AT,
            )
    assert _count(model_engine, "model.feature_row") == 0
    assert _count(model_engine, "model.prediction") == 0
    assert _count(model_engine, "model.metric") == 0


def test_prune_keeps_newest_runs_and_orphaned_vectors_go(model_engine: Engine) -> None:
    older, newer = _run(), _run()
    _write(model_engine, older)
    with model_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE model.prediction SET predicted_at = predicted_at - "
                "interval '1 day' WHERE run_id = :run_id"
            ),
            {"run_id": older.run_id},
        )
    _write(model_engine, newer)

    with model_engine.begin() as conn:
        dry = prune_runs(conn, keep=1, dry_run=True)
    assert dry.deleted_runs == (older.run_id,)
    assert dry.predictions_deleted == 0

    with model_engine.begin() as conn:
        summary = prune_runs(conn, keep=1, dry_run=False)
    assert summary.kept_runs == (newer.run_id,)
    assert summary.predictions_deleted == len(older.predictions)
    assert summary.feature_rows_deleted == 0
