"""Both boosters fit a tiny matrix that contains NaNs."""

from __future__ import annotations

import numpy as np

from models.rush_yards.estimators import fit_lightgbm, fit_xgboost, predict_finite


def test_boosters_fit_predict_on_nan_matrix() -> None:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(20, 8)).astype(np.float64)
    X[0, 1] = np.nan
    X[4, 3] = np.nan
    X[9, 0] = np.nan
    y = (X[:, 2] * 3.0 + rng.normal(scale=0.1, size=20)).astype(np.float64)
    y[0] = 1.0

    xgb = fit_xgboost(X, y, n_estimators=5)
    lgb = fit_lightgbm(X, y, n_estimators=5)

    xgb_hat = predict_finite(xgb, X)
    lgb_hat = predict_finite(lgb, X)

    assert len(xgb_hat) == 20
    assert len(lgb_hat) == 20
    assert all(math_isfinite(v) for v in xgb_hat)
    assert all(math_isfinite(v) for v in lgb_hat)


def math_isfinite(value: float) -> bool:
    return np.isfinite(value).item()
