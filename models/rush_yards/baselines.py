"""Mandatory point baselines. Never invent 0 for Unknown."""

from __future__ import annotations

from features.rush_yards import RushRbV1
from features.types import Known


def baseline_std(features: RushRbV1) -> float | None:
    """Season-to-date yards per game; week-1 / Unknown std uses prior season.

    Returns ``None`` when the predictor is Unknown (no std and no prior-season
    yards). Callers store that as a null ``y_hat`` and increment ``n_unknown``.
    """
    std = features.player_std_rush_yards
    if isinstance(std, Known):
        return float(std.value)
    prior = features.player_prior_season_rush_yards_pg
    if isinstance(prior, Known):
        return float(prior.value)
    return None


def baseline_last4(features: RushRbV1) -> float | None:
    """Mean rushing yards over the last 4 played games, or Unknown."""
    last4 = features.player_last4_rush_yards_pg
    if isinstance(last4, Known):
        return float(last4.value)
    return None
