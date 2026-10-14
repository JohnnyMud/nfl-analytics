"""Time-aware walk-forward. Cutoff is the earliest kickoff in the scored week."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from uuid import UUID, uuid4

from models.rush_yards.baselines import baseline_last4, baseline_std
from models.rush_yards.estimators import (
    DEFAULT_EARLY_STOPPING_ROUNDS,
    DEFAULT_N_ESTIMATORS,
    FEATURE_SET_VERSION,
    LGBM_MODEL_VERSION,
    XGB_MODEL_VERSION,
    booster_model_version,
    fit_lightgbm,
    fit_xgboost,
    predict_finite,
)
from models.rush_yards.matrix import FEATURE_SUBSETS, build_matrix, fit_category_encoder
from models.rush_yards.metrics import compute_metrics
from models.rush_yards.types import (
    FeatureSubset,
    LabeledRushRow,
    MetricRecord,
    ModelName,
    PendingRushRow,
    PredictionRecord,
    WalkForwardFold,
    WalkForwardResult,
)

SCORE_START_DEFAULT = 2016
SCORE_END_DEFAULT = 2025

BASELINE_STD_VERSION = "baseline_std_v1"
BASELINE_LAST4_VERSION = "baseline_last4_v1"


def walk_forward(
    rows: Sequence[LabeledRushRow],
    *,
    predicted_at: datetime,
    score_start: int = SCORE_START_DEFAULT,
    score_end: int = SCORE_END_DEFAULT,
    feature_subset: FeatureSubset = "full",
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
    run_id: UUID | None = None,
) -> WalkForwardResult:
    """Score each REG week in ``score_start``..``score_end``.

    Cutoff is data-derived (min kickoff in the test week). ``predicted_at`` is
    the wall-clock instant the caller is producing rows; it is provenance, not
    a feature, and is never read from the clock here. Same-game box scores are
    labels (``y_true``) only.
    """
    if score_start > score_end:
        raise ValueError("score_start must be <= score_end")
    _require_aware(predicted_at, "predicted_at")

    resolved_run = run_id or uuid4()
    validated = tuple(_validate_row(row) for row in rows)
    folds = tuple(
        iter_week_folds(validated, score_start=score_start, score_end=score_end)
    )

    predictions: list[PredictionRecord] = []
    for fold in folds:
        predictions.extend(
            _score(
                train=fold.train,
                eval_rows=fold.eval_rows,
                test=fold.test,
                run_id=resolved_run,
                predicted_at=predicted_at,
                feature_subset=feature_subset,
                n_estimators=n_estimators,
                early_stopping_rounds=early_stopping_rounds,
            )
        )
    return WalkForwardResult(
        run_id=resolved_run,
        feature_subset=feature_subset,
        predictions=tuple(predictions),
        metrics=tuple(_metrics_from_predictions(resolved_run, predictions)),
        folds=folds,
    )


def predict_pending(
    history: Sequence[LabeledRushRow],
    pending: Sequence[PendingRushRow],
    *,
    predicted_at: datetime,
    feature_subset: FeatureSubset = "pregame_safe",
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
    run_id: UUID | None = None,
) -> tuple[PredictionRecord, ...]:
    """Fit on games that kicked off before the earliest pending kickoff.

    Every pending row must kick off at or after that cutoff, so no training
    label comes from the week being predicted. Predictions carry no label.
    """
    _require_aware(predicted_at, "predicted_at")
    if not pending:
        return ()
    for row in pending:
        _validate_row(row)
    cutoff = min(row.kickoff_at for row in pending)
    validated = tuple(_validate_row(row) for row in history)
    train = tuple(row for row in validated if row.kickoff_at < cutoff)
    if not train:
        raise ValueError("no labeled history before the pending week")
    latest_season = max(row.season for row in train)
    eval_rows = tuple(row for row in train if row.season == latest_season - 1)
    return tuple(
        _score(
            train=train,
            eval_rows=eval_rows,
            test=tuple(pending),
            run_id=run_id or uuid4(),
            predicted_at=predicted_at,
            feature_subset=feature_subset,
            n_estimators=n_estimators,
            early_stopping_rounds=early_stopping_rounds,
        )
    )


def iter_week_folds(
    rows: Sequence[LabeledRushRow],
    *,
    score_start: int,
    score_end: int,
) -> Iterator[WalkForwardFold]:
    """Yield one fold per scored (season, week) that has population games."""
    by_week: dict[tuple[int, int], list[LabeledRushRow]] = {}
    for row in rows:
        by_week.setdefault((row.season, row.week), []).append(row)

    weeks = sorted(
        (season, week) for season, week in by_week if score_start <= season <= score_end
    )
    for season, week in weeks:
        test = tuple(by_week[(season, week)])
        cutoff = min(row.kickoff_at for row in test)
        train = tuple(row for row in rows if row.kickoff_at < cutoff)
        # Previous regular season, still strictly before the test-week cutoff
        # so a mis-dated fixture cannot leak the walk-forward week into eval.
        eval_rows = tuple(
            row for row in rows if row.season == season - 1 and row.kickoff_at < cutoff
        )
        yield WalkForwardFold(
            season=season,
            week=week,
            cutoff=cutoff,
            train=train,
            eval_rows=eval_rows,
            test=test,
        )


def _validate_row[R: (LabeledRushRow, PendingRushRow)](row: R) -> R:
    _require_aware(row.kickoff_at, "kickoff_at")
    _require_aware(row.features.as_of, "features.as_of")
    if row.gsis_id != row.features.gsis_id:
        raise ValueError("features.gsis_id must match the labeled row")
    if row.game_id != row.features.game_id:
        raise ValueError("features.game_id must match the labeled row")
    if row.kickoff_at != row.features.as_of:
        raise ValueError("features.as_of must equal kickoff_at")
    return row


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")


def _score(
    *,
    train: Sequence[LabeledRushRow],
    eval_rows: Sequence[LabeledRushRow],
    test: Sequence[LabeledRushRow | PendingRushRow],
    run_id: UUID,
    predicted_at: datetime,
    feature_subset: FeatureSubset,
    n_estimators: int,
    early_stopping_rounds: int,
) -> list[PredictionRecord]:
    predictions: list[PredictionRecord] = []
    for row in test:
        predictions.append(
            _prediction(
                row,
                run_id=run_id,
                predicted_at=predicted_at,
                model_name="baseline_std",
                model_version=BASELINE_STD_VERSION,
                y_hat=baseline_std(row.features),
            )
        )
        predictions.append(
            _prediction(
                row,
                run_id=run_id,
                predicted_at=predicted_at,
                model_name="baseline_last4",
                model_version=BASELINE_LAST4_VERSION,
                y_hat=baseline_last4(row.features),
            )
        )

    if not train:
        return predictions

    names = FEATURE_SUBSETS[feature_subset]
    train_features = [row.features for row in train]
    encoder = fit_category_encoder(train_features)
    train_matrix = build_matrix(
        train_features,
        y=[row.y_true for row in train],
        encoder=encoder,
        feature_names=names,
    )
    test_matrix = build_matrix(
        [row.features for row in test],
        encoder=encoder,
        feature_names=names,
    )
    assert train_matrix.y is not None

    eval_set = None
    if eval_rows:
        eval_matrix = build_matrix(
            [row.features for row in eval_rows],
            y=[row.y_true for row in eval_rows],
            encoder=encoder,
            feature_names=names,
        )
        if eval_matrix.y is not None and eval_matrix.X.shape[0] > 0:
            eval_set = (eval_matrix.X, eval_matrix.y)

    xgb = fit_xgboost(
        train_matrix.X,
        train_matrix.y,
        n_estimators=n_estimators,
        eval_set=eval_set,
        early_stopping_rounds=early_stopping_rounds,
    )
    lgb = fit_lightgbm(
        train_matrix.X,
        train_matrix.y,
        n_estimators=n_estimators,
        eval_set=eval_set,
        early_stopping_rounds=early_stopping_rounds,
        categorical_indices=train_matrix.categorical_indices,
    )
    xgb_version = booster_model_version(XGB_MODEL_VERSION, feature_subset)
    lgb_version = booster_model_version(LGBM_MODEL_VERSION, feature_subset)
    xgb_hat = predict_finite(xgb, test_matrix.X)
    lgb_hat = predict_finite(lgb, test_matrix.X)
    for row, x_hat, l_hat in zip(test, xgb_hat, lgb_hat, strict=True):
        predictions.append(
            _prediction(
                row,
                run_id=run_id,
                predicted_at=predicted_at,
                model_name="xgboost",
                model_version=xgb_version,
                y_hat=x_hat,
            )
        )
        predictions.append(
            _prediction(
                row,
                run_id=run_id,
                predicted_at=predicted_at,
                model_name="lightgbm",
                model_version=lgb_version,
                y_hat=l_hat,
            )
        )
    return predictions


def _prediction(
    row: LabeledRushRow | PendingRushRow,
    *,
    run_id: UUID,
    predicted_at: datetime,
    model_name: ModelName,
    model_version: str,
    y_hat: float | None,
) -> PredictionRecord:
    return PredictionRecord(
        run_id=run_id,
        model_name=model_name,
        model_version=model_version,
        feature_set_version=FEATURE_SET_VERSION,
        gsis_id=row.gsis_id,
        game_id=row.game_id,
        as_of=row.kickoff_at,
        y_hat=y_hat,
        y_true=row.y_true,
        predicted_at=predicted_at,
        season=row.season,
        week=row.week,
    )


def _metrics_from_predictions(
    run_id: UUID, predictions: Sequence[PredictionRecord]
) -> list[MetricRecord]:
    by_model: dict[ModelName, list[PredictionRecord]] = {}
    for pred in predictions:
        by_model.setdefault(pred.model_name, []).append(pred)

    records: list[MetricRecord] = []
    for model_name, group in by_model.items():
        records.append(_metric_row(run_id, model_name, group, season=None))
        seasons = sorted({pred.season for pred in group})
        for season in seasons:
            season_group = [pred for pred in group if pred.season == season]
            records.append(_metric_row(run_id, model_name, season_group, season=season))
    return records


def _metric_row(
    run_id: UUID,
    model_name: ModelName,
    group: Sequence[PredictionRecord],
    *,
    season: int | None,
) -> MetricRecord:
    labels: list[float] = []
    for pred in group:
        if pred.y_true is None:
            raise ValueError("walk-forward metrics require labeled predictions")
        labels.append(pred.y_true)
    stats = compute_metrics(labels, [pred.y_hat for pred in group])
    return MetricRecord(
        run_id=run_id,
        model_name=model_name,
        season=season,
        mae=stats.mae,
        rmse=stats.rmse,
        n=stats.n,
        n_unknown=stats.n_unknown,
    )
