"""Baseline_std and baseline_last4 never invent 0 for Unknown."""

from __future__ import annotations

from features.types import Known, Unknown
from models.rush_yards.baselines import baseline_last4, baseline_std
from models.rush_yards.metrics import compute_metrics
from tests.models.helpers import RB_A, RB_B, labeled_row


def test_week1_without_prior_season_is_unknown_std() -> None:
    row = labeled_row(RB_B, 2016, 1)
    assert isinstance(row.features.player_std_rush_yards, Unknown)
    assert isinstance(row.features.player_prior_season_rush_yards_pg, Unknown)
    assert baseline_std(row.features) is None
    assert baseline_last4(row.features) is None

    stats = compute_metrics([row.y_true], [baseline_std(row.features)])
    assert stats.n == 0
    assert stats.n_unknown == 1


def test_week1_with_prior_season_uses_prior_for_baseline_std() -> None:
    row = labeled_row(RB_A, 2016, 1)
    assert isinstance(row.features.player_std_rush_yards, Unknown)
    assert isinstance(row.features.player_prior_season_rush_yards_pg, Known)
    expected = (50 + 70 + 90) / 3
    assert row.features.player_prior_season_rush_yards_pg.value == expected
    assert baseline_std(row.features) == expected
    # Last-4 can still use 2015 played games.
    assert baseline_last4(row.features) == expected


def test_in_season_std_uses_season_to_date_not_zero() -> None:
    row = labeled_row(RB_A, 2016, 2)
    assert isinstance(row.features.player_std_rush_yards, Known)
    assert baseline_std(row.features) == 60.0
    assert baseline_std(row.features) != 0.0
    assert baseline_last4(row.features) is not None
