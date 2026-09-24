"""Matrix encoding: Known stays numeric; Unknown and unseen categories are NaN."""

from __future__ import annotations

import math

import numpy as np

from features.types import Known, Unknown
from models.rush_yards.matrix import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    MISSING_CATEGORY_CODE,
    build_matrix,
    fit_category_encoder,
)
from tests.models.helpers import RB_A, labeled_row


def _col(name: str) -> int:
    return FEATURE_NAMES.index(name)


def test_known_values_appear_unknown_is_nan_not_zero() -> None:
    week1 = labeled_row(RB_A, 2016, 1)
    week2 = labeled_row(RB_A, 2016, 2)

    assert isinstance(week1.features.player_std_rush_yards, Unknown)
    assert isinstance(week2.features.player_std_rush_yards, Known)
    assert week2.features.player_std_rush_yards.value == 60.0
    assert isinstance(week1.features.player_prior_games_this_season, Known)
    assert week1.features.player_prior_games_this_season.value == 0

    matrix = build_matrix([week1.features, week2.features])
    std_col = _col("player_std_rush_yards")
    prior_games_col = _col("player_prior_games_this_season")

    assert math.isnan(matrix.X[0, std_col])
    assert matrix.X[0, std_col] != 0
    assert matrix.X[1, std_col] == 60.0
    # 0 prior games this season is a Known count, not missing.
    assert matrix.X[0, prior_games_col] == 0.0
    assert not math.isnan(matrix.X[0, prior_games_col])


def test_unseen_training_category_is_missing_in_test_matrix() -> None:
    train = labeled_row(RB_A, 2016, 2, roof="outdoors", report_status="Questionable")
    test = labeled_row(RB_A, 2016, 3, roof="retractable", report_status="Out")

    encoder = fit_category_encoder([train.features])
    assert encoder.levels["roof"] == ("outdoors",)
    assert "retractable" not in encoder.levels["roof"]
    assert encoder.code("roof", "retractable") is not None
    assert math.isnan(encoder.code("roof", "retractable"))
    assert MISSING_CATEGORY_CODE == -1

    train_matrix = build_matrix([train.features], encoder=encoder)
    test_matrix = build_matrix([test.features], encoder=encoder)

    roof_col = _col("roof")
    status_col = _col("report_status")
    assert train_matrix.X[0, roof_col] == 0.0
    assert math.isnan(test_matrix.X[0, roof_col])
    assert math.isnan(test_matrix.X[0, status_col])
    assert not np.isfinite(test_matrix.X[0, roof_col])

    for name in CATEGORICAL_FEATURES:
        assert name in FEATURE_NAMES
