"""Walk-forward is time-aware: cutoff is the week's earliest kickoff."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from models.rush_yards.walk_forward import iter_week_folds, walk_forward
from tests.models.helpers import RB_A, RB_B, labeled_row, population

PREDICTED_AT = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)


def test_week2_train_kickoffs_are_strictly_before_cutoff() -> None:
    rows = population()
    folds = list(iter_week_folds(rows, score_start=2016, score_end=2016))
    week2 = next(fold for fold in folds if fold.week == 2)

    expected_cutoff = min(
        row.kickoff_at for row in rows if row.season == 2016 and row.week == 2
    )
    assert week2.cutoff == expected_cutoff
    assert week2.cutoff == datetime(2016, 9, 18, 17, 0, tzinfo=UTC)
    assert week2.train
    assert all(row.kickoff_at < week2.cutoff for row in week2.train)
    assert all(row.kickoff_at < week2.cutoff for row in week2.eval_rows)


def test_week3_is_absent_from_week2_train_and_eval() -> None:
    rows = population()
    folds = list(iter_week_folds(rows, score_start=2016, score_end=2016))
    week2 = next(fold for fold in folds if fold.week == 2)

    leaked = [
        row
        for row in (*week2.train, *week2.eval_rows)
        if row.season == 2016 and row.week == 3
    ]
    assert leaked == []
    assert all(not (row.season == 2016 and row.week == 3) for row in week2.train)
    assert all(not (row.season == 2016 and row.week == 3) for row in week2.eval_rows)
    week3_ids = {
        (row.gsis_id, row.game_id)
        for row in rows
        if row.season == 2016 and row.week == 3
    }
    seen = {(row.gsis_id, row.game_id) for row in (*week2.train, *week2.eval_rows)}
    assert week3_ids.isdisjoint(seen)
    assert {(row.gsis_id, row.game_id) for row in week2.test} == {
        (RB_A, labeled_row(RB_A, 2016, 2).game_id),
        (RB_B, labeled_row(RB_B, 2016, 2).game_id),
    }


def test_walk_forward_emits_baselines_and_boosters_with_small_n_estimators() -> None:
    rows = population()
    result = walk_forward(
        rows,
        predicted_at=PREDICTED_AT,
        score_start=2016,
        score_end=2016,
        n_estimators=5,
    )
    names = {pred.model_name for pred in result.predictions}
    assert names == {"xgboost", "lightgbm", "baseline_std", "baseline_last4"}

    week2_fold = next(fold for fold in result.folds if fold.week == 2)
    assert all(row.kickoff_at < week2_fold.cutoff for row in week2_fold.train)
    assert all(not (row.season == 2016 and row.week == 3) for row in week2_fold.train)

    booster = [
        pred
        for pred in result.predictions
        if pred.model_name in {"xgboost", "lightgbm"}
    ]
    assert booster
    assert all(pred.y_hat is not None for pred in booster)
    assert all(pred.feature_set_version == "rush_rb_v1" for pred in result.predictions)
    assert all(pred.as_of.tzinfo is not None for pred in result.predictions)

    overall = [metric for metric in result.metrics if metric.season is None]
    assert {metric.model_name for metric in overall} == names
    season_2016 = [metric for metric in result.metrics if metric.season == 2016]
    assert season_2016


def test_walk_forward_baseline_unknown_increments_n_unknown() -> None:
    rows = [labeled_row(RB_B, 2016, 1)]
    result = walk_forward(
        rows,
        predicted_at=PREDICTED_AT,
        score_start=2016,
        score_end=2016,
        n_estimators=5,
    )
    std_metrics = [
        metric
        for metric in result.metrics
        if metric.model_name == "baseline_std" and metric.season is None
    ]
    assert len(std_metrics) == 1
    assert std_metrics[0].n_unknown >= 1
    std_preds = [
        pred for pred in result.predictions if pred.model_name == "baseline_std"
    ]
    assert std_preds[0].y_hat is None


def test_naive_feature_as_of_is_rejected() -> None:
    row = labeled_row(RB_A, 2016, 2)
    naive_features = row.features.model_copy(
        update={"as_of": datetime(2016, 9, 18, 17, 0)}
    )
    bad = row.model_copy(update={"features": naive_features})
    with pytest.raises(ValueError, match="timezone-aware"):
        walk_forward(
            [bad],
            predicted_at=PREDICTED_AT,
            score_start=2016,
            score_end=2016,
            n_estimators=5,
        )
