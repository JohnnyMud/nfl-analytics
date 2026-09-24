"""The walkthrough demo trains only on earlier kickoffs."""

from __future__ import annotations

from backtest.rush_yards_demo import (
    RB_A,
    demo_population,
    predict_player_game,
    run_walk_forward,
)


def test_demo_walk_forward_scores_2016_only() -> None:
    result = run_walk_forward(n_estimators=5)
    assert {pred.season for pred in result.predictions} == {2016}
    booster = [
        pred
        for pred in result.predictions
        if pred.model_name in {"xgboost", "lightgbm"}
    ]
    assert booster
    assert all(pred.y_hat is not None for pred in booster)


def test_held_out_prediction_does_not_use_that_game() -> None:
    rows = demo_population()
    target = next(
        row
        for row in rows
        if row.gsis_id == RB_A and row.season == 2016 and row.week == 3
    )
    out = predict_player_game(rows, RB_A, 2016, 3, n_estimators=5)
    assert out["game_id"] == target.game_id
    assert out["y_true"] == target.y_true
    assert out["n_train"] == sum(row.kickoff_at < target.kickoff_at for row in rows)
    assert isinstance(out["xgboost_y_hat"], float)
    assert isinstance(out["lightgbm_y_hat"], float)
