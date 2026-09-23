"""Fixed-seed XGBoost and LightGBM regressors. Spec §8 parameters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
from lightgbm import LGBMRegressor, early_stopping
from numpy.typing import NDArray
from xgboost import XGBRegressor

FEATURE_SET_VERSION = "rush_rb_v1"
XGB_MODEL_VERSION = "xgb_rush_rb_v1"
LGBM_MODEL_VERSION = "lgbm_rush_rb_v1"

DEFAULT_N_ESTIMATORS = 400
DEFAULT_EARLY_STOPPING_ROUNDS = 25


def make_xgboost(
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    early_stopping_rounds: int | None = None,
) -> XGBRegressor:
    kwargs: dict[str, int | float | str | bool] = {
        "n_estimators": n_estimators,
        "max_depth": 4,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "n_jobs": 1,
        "tree_method": "hist",
        "enable_categorical": True,
        "verbosity": 0,
    }
    if early_stopping_rounds is not None:
        kwargs["early_stopping_rounds"] = early_stopping_rounds
    return XGBRegressor(**kwargs)


def make_lightgbm(*, n_estimators: int = DEFAULT_N_ESTIMATORS) -> LGBMRegressor:
    return LGBMRegressor(
        n_estimators=n_estimators,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=1,
        verbose=-1,
    )


def fit_xgboost(
    X: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    eval_set: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
) -> XGBRegressor:
    """Fit XGBRegressor. Early stopping only when ``eval_set`` is non-empty."""
    use_eval = eval_set is not None and eval_set[0].shape[0] > 0
    model = make_xgboost(
        n_estimators=n_estimators,
        early_stopping_rounds=early_stopping_rounds if use_eval else None,
    )
    if use_eval:
        assert eval_set is not None
        model.fit(X, y, eval_set=[(eval_set[0], eval_set[1])], verbose=False)
    else:
        model.fit(X, y, verbose=False)
    return model


def fit_lightgbm(
    X: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    eval_set: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
    categorical_indices: Sequence[int] | None = None,
) -> LGBMRegressor:
    """Fit LGBMRegressor. Early stopping only when ``eval_set`` is non-empty."""
    use_eval = eval_set is not None and eval_set[0].shape[0] > 0
    model = make_lightgbm(n_estimators=n_estimators)
    cat_feature: list[int] | Literal["auto"] = (
        list(categorical_indices) if categorical_indices else "auto"
    )
    if use_eval:
        assert eval_set is not None
        model.fit(
            X,
            y,
            eval_set=[(eval_set[0], eval_set[1])],
            categorical_feature=cat_feature,
            callbacks=[early_stopping(early_stopping_rounds, verbose=False)],
        )
    else:
        model.fit(X, y, categorical_feature=cat_feature)
    return model


def predict_finite(
    model: XGBRegressor | LGBMRegressor, X: NDArray[np.float64]
) -> list[float]:
    raw = np.asarray(model.predict(X), dtype=np.float64)
    if raw.shape[0] != X.shape[0]:
        raise ValueError("predict length does not match X")
    return [float(value) for value in raw]
