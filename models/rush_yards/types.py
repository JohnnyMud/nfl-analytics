"""Pydantic boundary types for labeled rows, predictions, and metrics."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from features.rush_yards import RushRbV1

ModelName = Literal["xgboost", "lightgbm", "baseline_std", "baseline_last4"]


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


class PredictionRecord(BaseModel):
    """One stored prediction. ``season`` / ``week`` are in-memory only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    model_name: ModelName
    model_version: str
    feature_set_version: str
    gsis_id: str
    game_id: str
    as_of: AwareDatetime
    y_hat: float | None
    y_true: float
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
    predictions: tuple[PredictionRecord, ...]
    metrics: tuple[MetricRecord, ...]
    folds: tuple[WalkForwardFold, ...]
