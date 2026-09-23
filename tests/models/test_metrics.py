"""Hand-computed MAE / RMSE; Unknown predictions are excluded from n."""

from __future__ import annotations

import math

from models.rush_yards.metrics import compute_metrics


def test_mae_rmse_match_hand_computed_pair() -> None:
    y_true = [10.0, 20.0, 30.0]
    y_hat = [12.0, None, 25.0]
    stats = compute_metrics(y_true, y_hat)

    assert stats.n == 2
    assert stats.n_unknown == 1
    assert stats.mae == 3.5
    assert stats.rmse == math.sqrt((4.0 + 25.0) / 2.0)


def test_all_unknown_counts_n_unknown_and_keeps_mae_defined() -> None:
    stats = compute_metrics([8.0, 12.0], [None, None])
    assert stats.n == 0
    assert stats.n_unknown == 2
    assert stats.mae == 0.0
    assert stats.rmse == 0.0
