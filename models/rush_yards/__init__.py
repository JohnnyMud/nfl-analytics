"""Rush yards point models. Reads in-memory feature rows, never raw SQL tables."""

from models.rush_yards.baselines import baseline_last4, baseline_std
from models.rush_yards.estimators import (
    FEATURE_SET_VERSION,
    LGBM_MODEL_VERSION,
    XGB_MODEL_VERSION,
    fit_lightgbm,
    fit_xgboost,
    make_lightgbm,
    make_xgboost,
)
from models.rush_yards.matrix import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    MISSING_CATEGORY_CODE,
    CategoryEncoder,
    FeatureMatrix,
    build_matrix,
    fit_category_encoder,
)
from models.rush_yards.metrics import MetricStats, compute_metrics
from models.rush_yards.payload import features_to_payload, payload_to_features
from models.rush_yards.types import (
    LabeledRushRow,
    MetricRecord,
    ModelName,
    PredictionRecord,
    WalkForwardFold,
    WalkForwardResult,
)
from models.rush_yards.walk_forward import iter_week_folds, walk_forward

__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_NAMES",
    "FEATURE_SET_VERSION",
    "MISSING_CATEGORY_CODE",
    "LGBM_MODEL_VERSION",
    "XGB_MODEL_VERSION",
    "CategoryEncoder",
    "FeatureMatrix",
    "LabeledRushRow",
    "MetricRecord",
    "MetricStats",
    "ModelName",
    "PredictionRecord",
    "WalkForwardFold",
    "WalkForwardResult",
    "baseline_last4",
    "baseline_std",
    "build_matrix",
    "compute_metrics",
    "features_to_payload",
    "fit_category_encoder",
    "fit_lightgbm",
    "fit_xgboost",
    "iter_week_folds",
    "make_lightgbm",
    "make_xgboost",
    "payload_to_features",
    "walk_forward",
]
