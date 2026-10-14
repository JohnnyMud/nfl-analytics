"""Feature subsets, prediction provenance, and unlabeled upcoming predictions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from models.rush_yards.matrix import (
    FEATURE_NAMES,
    FEATURE_SUBSETS,
    NOT_PREGAME_VERIFIED,
    build_matrix,
)
from models.rush_yards.types import PendingRushRow
from models.rush_yards.walk_forward import (
    iter_week_folds,
    predict_pending,
    walk_forward,
)
from tests.models.helpers import RB_A, labeled_row, population

PREDICTED_AT = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)


def test_pregame_safe_drops_only_unverified_features() -> None:
    safe = FEATURE_SUBSETS["pregame_safe"]
    assert set(FEATURE_NAMES) - set(safe) == NOT_PREGAME_VERIFIED
    assert FEATURE_SUBSETS["full"] == FEATURE_NAMES


def test_matrix_columns_follow_the_subset() -> None:
    rows = [row.features for row in population()]
    matrix = build_matrix(rows, feature_names=FEATURE_SUBSETS["pregame_safe"])
    assert matrix.feature_names == FEATURE_SUBSETS["pregame_safe"]
    assert matrix.X.shape[1] == len(FEATURE_SUBSETS["pregame_safe"])
    assert [matrix.feature_names[i] for i in matrix.categorical_indices] == [
        "roof",
        "surface",
    ]


def test_unregistered_feature_is_rejected() -> None:
    rows = [row.features for row in population()]
    with pytest.raises(ValueError, match="unregistered"):
        build_matrix(rows, feature_names=("player_std_rush_yards", "closing_line"))


def test_subset_is_part_of_booster_model_version_and_predicted_at_is_wall_clock() -> (
    None
):
    result = walk_forward(
        population(),
        predicted_at=PREDICTED_AT,
        score_start=2016,
        score_end=2016,
        feature_subset="pregame_safe",
        n_estimators=5,
    )
    versions = {
        pred.model_name: pred.model_version
        for pred in result.predictions
        if pred.model_name in {"xgboost", "lightgbm"}
    }
    assert versions == {
        "xgboost": "xgb_rush_rb_v1+pregame_safe",
        "lightgbm": "lgbm_rush_rb_v1+pregame_safe",
    }
    assert result.feature_subset == "pregame_safe"
    assert all(pred.predicted_at == PREDICTED_AT for pred in result.predictions)
    assert all(pred.as_of != pred.predicted_at for pred in result.predictions)


def test_naive_predicted_at_is_rejected() -> None:
    with pytest.raises(ValueError, match="predicted_at"):
        walk_forward(population(), predicted_at=datetime(2026, 10, 14), n_estimators=5)


def test_every_fold_trains_strictly_before_its_test_week() -> None:
    folds = list(iter_week_folds(population(), score_start=2015, score_end=2016))
    assert folds
    for fold in folds:
        if fold.train:
            assert max(row.kickoff_at for row in fold.train) < min(
                row.kickoff_at for row in fold.test
            )


def _pending_week3() -> PendingRushRow:
    row = labeled_row(RB_A, 2016, 3)
    return PendingRushRow(
        gsis_id=row.gsis_id,
        game_id=row.game_id,
        season=row.season,
        week=row.week,
        kickoff_at=row.kickoff_at,
        features=row.features,
    )


def test_pending_predictions_have_no_label_and_ignore_same_week_history() -> None:
    pending = _pending_week3()
    history = population()
    with_week3 = predict_pending(
        history, [pending], predicted_at=PREDICTED_AT, n_estimators=5
    )
    without_week3 = predict_pending(
        [row for row in history if row.week != 3 or row.season != 2016],
        [pending],
        predicted_at=PREDICTED_AT,
        n_estimators=5,
    )
    assert all(pred.y_true is None for pred in with_week3)
    assert {pred.model_name for pred in with_week3} == {
        "baseline_std",
        "baseline_last4",
        "xgboost",
        "lightgbm",
    }
    # The 2016 week-3 label is in ``history`` but kicks off at the cutoff, so it
    # cannot change the fit.
    assert [pred.y_hat for pred in with_week3] == [pred.y_hat for pred in without_week3]


def test_pending_without_history_raises() -> None:
    with pytest.raises(ValueError, match="no labeled history"):
        predict_pending([], [_pending_week3()], predicted_at=PREDICTED_AT)
