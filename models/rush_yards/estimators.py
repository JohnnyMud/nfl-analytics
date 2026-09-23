"""Fixed-seed XGBoost and LightGBM regressors. Spec §8 parameters.

``XGBRegressor`` / ``LGBMRegressor`` are sklearn wrappers and raise unless
scikit-learn is installed. Spec §8 forbids adding sklearn as a runtime
dependency, so we apply the same hyperparameters through ``xgboost.train``
and ``lightgbm.train``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
from lightgbm import Dataset
from lightgbm import train as lgb_train
from lightgbm.callback import early_stopping
from numpy.typing import NDArray
from xgboost import DMatrix
from xgboost import train as xgb_train

FEATURE_SET_VERSION = "rush_rb_v1"
XGB_MODEL_VERSION = "xgb_rush_rb_v1"
LGBM_MODEL_VERSION = "lgbm_rush_rb_v1"

DEFAULT_N_ESTIMATORS = 400
DEFAULT_EARLY_STOPPING_ROUNDS = 25


@dataclass(frozen=True, slots=True)
class XGBRegressorSpec:
    """``xgboost.XGBRegressor`` kwargs from spec §8."""

    n_estimators: int = DEFAULT_N_ESTIMATORS
    max_depth: int = 4
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42
    n_jobs: int = 1
    tree_method: str = "hist"
    enable_categorical: bool = True
    early_stopping_rounds: int | None = None


@dataclass(frozen=True, slots=True)
class LGBMRegressorSpec:
    """``lightgbm.LGBMRegressor`` kwargs from spec §8."""

    n_estimators: int = DEFAULT_N_ESTIMATORS
    max_depth: int = 4
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42
    n_jobs: int = 1


@dataclass(frozen=True, slots=True)
class FittedBooster:
    """Native booster with an ndarray ``predict`` path."""

    kind: str
    booster: object

    def predict(self, X: NDArray[np.float64]) -> NDArray[np.float64]:
        if self.kind == "xgboost":
            raw = self.booster.predict(DMatrix(X, missing=np.nan))  # type: ignore[attr-defined]
        else:
            raw = self.booster.predict(X)  # type: ignore[attr-defined]
        return np.asarray(raw, dtype=np.float64)


def make_xgboost(
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    early_stopping_rounds: int | None = None,
) -> XGBRegressorSpec:
    return XGBRegressorSpec(
        n_estimators=n_estimators,
        early_stopping_rounds=early_stopping_rounds,
    )


def make_lightgbm(*, n_estimators: int = DEFAULT_N_ESTIMATORS) -> LGBMRegressorSpec:
    return LGBMRegressorSpec(n_estimators=n_estimators)


def fit_xgboost(
    X: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    eval_set: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
) -> FittedBooster:
    """Fit the spec XGBoost regressor. Early stop only when eval is non-empty."""
    spec = make_xgboost(
        n_estimators=n_estimators,
        early_stopping_rounds=early_stopping_rounds,
    )
    params: dict[str, int | float | str | bool] = {
        "max_depth": spec.max_depth,
        "learning_rate": spec.learning_rate,
        "subsample": spec.subsample,
        "colsample_bytree": spec.colsample_bytree,
        "seed": spec.random_state,
        "nthread": spec.n_jobs,
        "tree_method": spec.tree_method,
        "enable_categorical": spec.enable_categorical,
        "verbosity": 0,
        "objective": "reg:squarederror",
    }
    dtrain = DMatrix(X, label=y, missing=np.nan)
    use_eval = eval_set is not None and eval_set[0].shape[0] > 0
    evals: list[tuple[DMatrix, str]] = []
    if use_eval:
        assert eval_set is not None
        evals = [(DMatrix(eval_set[0], label=eval_set[1], missing=np.nan), "eval")]
    booster = xgb_train(
        params,
        dtrain,
        num_boost_round=spec.n_estimators,
        evals=evals or None,
        early_stopping_rounds=early_stopping_rounds if use_eval else None,
        verbose_eval=False,
    )
    return FittedBooster(kind="xgboost", booster=booster)


def fit_lightgbm(
    X: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    eval_set: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
    categorical_indices: Sequence[int] | None = None,
) -> FittedBooster:
    """Fit the spec LightGBM regressor. Early stop only when eval is non-empty."""
    spec = make_lightgbm(n_estimators=n_estimators)
    params: dict[str, int | float | str] = {
        "objective": "regression",
        "max_depth": spec.max_depth,
        "learning_rate": spec.learning_rate,
        "subsample": spec.subsample,
        "colsample_bytree": spec.colsample_bytree,
        "seed": spec.random_state,
        "n_jobs": spec.n_jobs,
        "verbose": -1,
        "metric": "rmse",
    }
    cat: list[int] | Literal["auto"] = (
        list(categorical_indices) if categorical_indices else "auto"
    )
    train_set = Dataset(X, label=y, categorical_feature=cat, free_raw_data=False)
    use_eval = eval_set is not None and eval_set[0].shape[0] > 0
    valid_sets = None
    callbacks: list[Callable[..., Any]] | None = None
    if use_eval:
        assert eval_set is not None
        valid_sets = [
            Dataset(
                eval_set[0],
                label=eval_set[1],
                categorical_feature=cat,
                reference=train_set,
                free_raw_data=False,
            )
        ]
        callbacks = cast(
            list[Callable[..., Any]],
            [early_stopping(early_stopping_rounds, verbose=False)],
        )
    booster = lgb_train(
        params,
        train_set,
        num_boost_round=spec.n_estimators,
        valid_sets=valid_sets,
        callbacks=callbacks,
    )
    return FittedBooster(kind="lightgbm", booster=booster)


def predict_finite(model: FittedBooster, X: NDArray[np.float64]) -> list[float]:
    raw = model.predict(X)
    if raw.shape[0] != X.shape[0]:
        raise ValueError("predict length does not match X")
    return [float(value) for value in raw]
