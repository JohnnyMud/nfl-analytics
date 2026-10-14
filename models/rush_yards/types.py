"""Pydantic boundary types for labeled rows, predictions, and metrics."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from features.rush_yards import RushRbV1

ModelName = Literal["xgboost", "lightgbm", "baseline_std", "baseline_last4"]
FeatureSubset = Literal["full", "pregame_safe"]


class LabeledRushRow(BaseModel):
    """One in-population RB game with features already built at kickoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    game_id: str
    season: int
    week: int
    kickoff_at: AwareDatetime
    y_true: float
    features: RushRbV1


class PendingRushRow(BaseModel):
    """A game not yet played. Same keys as ``LabeledRushRow``, no label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gsis_id: str
    game_id: str
    season: int
    week: int
    kickoff_at: AwareDatetime
    features: RushRbV1

    @property
    def y_true(self) -> None:
        return None


class PredictionRecord(BaseModel):
    """One stored prediction. ``season`` / ``week`` are in-memory only.

    ``y_true`` is null for a game that had not been played when predicted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    model_name: ModelName
    model_version: str
    feature_set_version: str
    gsis_id: str
    game_id: str
    as_of: AwareDatetime
    y_hat: float | None
    y_true: float | None
    predicted_at: AwareDatetime
    season: int
    week: int


class MetricRecord(BaseModel):
    """MAE / RMSE for one model. ``season`` is None for overall."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    model_name: ModelName
    season: int | None
    mae: float
    rmse: float
    n: int
    n_unknown: int


class WalkForwardFold(BaseModel):
    """One scored REG week. Cutoff is the earliest kickoff in the test week."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int
    week: int
    cutoff: AwareDatetime
    train: tuple[LabeledRushRow, ...]
    eval_rows: tuple[LabeledRushRow, ...]
    test: tuple[LabeledRushRow, ...]


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    feature_subset: FeatureSubset
    predictions: tuple[PredictionRecord, ...]
    metrics: tuple[MetricRecord, ...]
    folds: tuple[WalkForwardFold, ...]
