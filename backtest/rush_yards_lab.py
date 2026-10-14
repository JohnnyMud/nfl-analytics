"""Feature lab for the rush yards model. Research only; writes nothing.

Used by ``backtest/rush_yards_lab.ipynb`` to try feature lists quickly and see
which features help. It refits LightGBM in memory, so it is not the harness:
numbers here are for choosing features, and a chosen list is confirmed with
``python -m models.rush_yards backtest`` before anyone quotes it.

Protocol (fixed before looking at results):

- Validation seasons are 2019-2024. Each fold trains on every regular-season
  RB game from earlier seasons and scores one whole season (one refit per
  season, not per week, so it runs in seconds). Early stopping uses the
  previous season, as in production.
- 2025 is the holdout. ``evaluate`` refuses it unless ``allow_holdout=True``;
  look at it once, after the feature list is final.
- Every fit is repeated over ``SEEDS`` and the predictions averaged. With a
  single seed, merely reordering the same 16 columns moves validation MAE by
  about 0.02 yards (standard deviation), and one order landed 0.06 worse than
  typical. Without averaging, that luck would read as a feature effect.
- Feature lists are compared on the same rows with a paired difference and a
  standard error clustered by (season, week), because a 0.1-yard gain is
  within noise more often than not.

Experimental features are functions of the point-in-time ``RushSnapshot``
the model already uses, so they cannot see the target game or anything after
it. Promote a winner into ``features/rush_yards.py`` as a new feature-set
version; never edit ``rush_rb_v1`` in place.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

import lightgbm
import numpy as np
import polars as pl
from numpy.typing import NDArray
from sqlalchemy import text
from sqlalchemy.engine import Engine

from features.rush_yards import RushSnapshot, build_rush_rb_v1
from features.rush_yards_source import (
    RushSnapshotIndex,
    RushTarget,
    load_rush_history,
    rb_population,
    targets_from_box_scores,
)
from models.rush_yards.baselines import baseline_last4, baseline_std
from models.rush_yards.estimators import fit_lightgbm
from models.rush_yards.matrix import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    FEATURE_SUBSETS,
    build_matrix,
)

VALIDATION_SEASONS: tuple[int, ...] = (2019, 2020, 2021, 2022, 2023, 2024)
HOLDOUT_SEASON = 2025
SEEDS: tuple[int, ...] = (0, 1, 2, 3, 4)
PREGAME_SAFE: tuple[str, ...] = FEATURE_SUBSETS["pregame_safe"]
FULL: tuple[str, ...] = FEATURE_SUBSETS["full"]

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "season_to_date": (
        "player_std_rush_yards",
        "player_std_carries",
        "player_std_ypc",
        "player_prior_games_this_season",
    ),
    "last_game": ("player_last_rush_yards", "player_last_carries"),
    "last4": ("player_last4_rush_yards_pg", "player_last4_carries_pg"),
    "prior_season": ("player_prior_season_rush_yards_pg",),
    "opponent": ("opp_std_rush_yards_allowed_pg", "opp_last4_rush_yards_allowed_pg"),
    "schedule": ("is_home", "rest_days", "div_game"),
    "venue": ("roof", "surface"),
    "weather": ("temp", "wind"),
    "injury": ("report_status", "practice_status"),
    "depth": ("depth_team",),
}

ExtraFeature = Callable[[RushSnapshot], float | None]


@dataclass
class LabData:
    """Every labeled RB game, one row each, with a registry matrix built once."""

    season: NDArray[np.int64]
    week: NDArray[np.int64]
    y: NDArray[np.float64]
    baseline_std: NDArray[np.float64]
    baseline_last4: NDArray[np.float64]
    columns: dict[str, NDArray[np.float64]]
    targets: list[RushTarget]
    index: RushSnapshotIndex
    keys: list[tuple[str, str]] = field(default_factory=list)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.columns)

    def matrix(self, names: Sequence[str]) -> NDArray[np.float64]:
        missing = [name for name in names if name not in self.columns]
        if missing:
            raise KeyError(f"unknown features (add them first): {missing}")
        return np.column_stack([self.columns[name] for name in names])


def load_lab_data(
    engine: Engine, *, season_start: int = 2016, season_end: int = HOLDOUT_SEASON
) -> LabData:
    """Read ``nfl.*`` once in a read-only transaction and build every row."""
    kickoff_before = datetime(season_end + 1, 3, 1, tzinfo=UTC)
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        history = load_rush_history(
            conn,
            season_start=season_start,
            season_end=season_end,
            kickoff_before=kickoff_before,
        )
    index = RushSnapshotIndex(history)
    boxes = rb_population(history, season_start=season_start, season_end=season_end)
    targets = targets_from_box_scores(boxes)
    features = [
        build_rush_rb_v1(target.gsis_id, target.as_of, index.snapshot(target))
        for target in targets
    ]
    # Integer codes only; which levels a fold may use is enforced per fold.
    registry = build_matrix(features, feature_names=FEATURE_NAMES)
    return LabData(
        season=np.array([box.season for box in boxes], dtype=np.int64),
        week=np.array([box.week for box in boxes], dtype=np.int64),
        y=np.array([float(box.rushing_yards) for box in boxes], dtype=np.float64),
        baseline_std=_nan_array([baseline_std(row) for row in features]),
        baseline_last4=_nan_array([baseline_last4(row) for row in features]),
        columns={name: registry.X[:, j].copy() for j, name in enumerate(FEATURE_NAMES)},
        targets=targets,
        index=index,
        keys=[(box.gsis_id, box.game_id) for box in boxes],
    )


def add_features(data: LabData, extras: Mapping[str, ExtraFeature]) -> None:
    """Compute experimental columns from each row's point-in-time snapshot.

    Each function sees only games that kicked off before the target game
    (``prior_player_games`` / ``prior_opponent_games``) plus the target's
    schedule context. ``snapshot.target.temp`` / ``wind`` are game-day
    actuals; do not use them in a pregame feature. Return ``None`` for
    unknown; it becomes NaN, never 0.
    """
    clash = [name for name in extras if name in FEATURE_NAMES]
    if clash:
        raise ValueError(f"names already in rush_rb_v1: {clash}")
    values: dict[str, list[float]] = {name: [] for name in extras}
    for target in data.targets:
        snapshot = data.index.snapshot(target)
        if any(g.kickoff_at >= target.as_of for g in snapshot.prior_player_games):
            raise AssertionError("snapshot leaked a game at or after kickoff")
        for name, fn in extras.items():
            value = fn(snapshot)
            values[name].append(np.nan if value is None else float(value))
    for name, column in values.items():
        data.columns[name] = np.asarray(column, dtype=np.float64)


@dataclass
class LabResult:
    """Out-of-sample LightGBM predictions for one feature list.

    ``boosters[season]`` holds one model per seed; ``y_hat`` is their mean.
    """

    features: tuple[str, ...]
    rows: NDArray[np.int64]
    y_hat: NDArray[np.float64]
    boosters: dict[int, list[lightgbm.Booster]]
    test_rows: dict[int, NDArray[np.int64]]
    train_rows: dict[int, NDArray[np.int64]]


def evaluate(
    data: LabData,
    features: Sequence[str],
    *,
    seasons: Sequence[int] = VALIDATION_SEASONS,
    allow_holdout: bool = False,
    n_estimators: int = 400,
    seeds: Sequence[int] = SEEDS,
) -> LabResult:
    """Per season, fit on all earlier seasons once per seed; predict the mean."""
    if HOLDOUT_SEASON in seasons and not allow_holdout:
        raise ValueError(
            f"{HOLDOUT_SEASON} is the holdout; pass allow_holdout=True once, at the end"
        )
    names = tuple(features)
    X_all = data.matrix(names)
    cat_idx = [j for j, name in enumerate(names) if name in CATEGORICAL_FEATURES]
    rows: list[NDArray[np.int64]] = []
    preds: list[NDArray[np.float64]] = []
    boosters: dict[int, list[lightgbm.Booster]] = {}
    test_rows: dict[int, NDArray[np.int64]] = {}
    train_rows: dict[int, NDArray[np.int64]] = {}
    for season in seasons:
        train = np.flatnonzero(data.season < season)
        test = np.flatnonzero(data.season == season)
        evals = np.flatnonzero(data.season == season - 1)
        X_train = X_all[train]
        X_test = _unseen_levels_to_nan(X_all[test], X_train, cat_idx)
        X_eval = _unseen_levels_to_nan(X_all[evals], X_train, cat_idx)
        fitted = [
            cast(
                lightgbm.Booster,
                fit_lightgbm(
                    X_train,
                    data.y[train],
                    n_estimators=n_estimators,
                    eval_set=(X_eval, data.y[evals]),
                    categorical_indices=cat_idx,
                    seed=seed,
                ).booster,
            )
            for seed in seeds
        ]
        rows.append(test)
        preds.append(_predict(fitted, X_test))
        boosters[season] = fitted
        test_rows[season] = test
        train_rows[season] = train
    return LabResult(
        features=names,
        rows=np.concatenate(rows),
        y_hat=np.concatenate(preds),
        boosters=boosters,
        test_rows=test_rows,
        train_rows=train_rows,
    )


def scores(data: LabData, result: LabResult) -> pl.DataFrame:
    """MAE / RMSE per season and overall for the model and both baselines.

    Baselines are scored on the rows where they are Known; ``n`` says how many.
    """
    out = []
    for season in [*sorted(result.test_rows), None]:
        mask = (
            np.ones(result.rows.shape[0], dtype=bool)
            if season is None
            else data.season[result.rows] == season
        )
        idx = result.rows[mask]
        y = data.y[idx]
        for name, y_hat in (
            ("lightgbm", result.y_hat[mask]),
            ("baseline_std", data.baseline_std[idx]),
            ("baseline_last4", data.baseline_last4[idx]),
        ):
            known = ~np.isnan(y_hat)
            err = y_hat[known] - y[known]
            out.append(
                {
                    "season": "overall" if season is None else str(season),
                    "model": name,
                    "mae": float(np.mean(np.abs(err))),
                    "rmse": float(np.sqrt(np.mean(err**2))),
                    "n": int(known.sum()),
                }
            )
    return pl.DataFrame(out)


def compare(data: LabData, a: LabResult, b: LabResult) -> pl.DataFrame:
    """Paired MAE change from ``a`` to ``b`` per season and overall.

    ``delta_mae`` < 0 means ``b`` is better. ``se`` is clustered by
    (season, week); treat |delta| < 2 se as no evidence either way.
    """
    if not np.array_equal(a.rows, b.rows):
        raise ValueError("results cover different rows; evaluate on the same seasons")
    y = data.y[a.rows]
    err_a = a.y_hat - y
    err_b = b.y_hat - y
    diff = np.abs(err_b) - np.abs(err_a)
    seasons = data.season[a.rows]
    weeks = data.week[a.rows]
    out = []
    for season in [*sorted(set(seasons.tolist())), None]:
        mask = (
            np.ones(diff.shape[0], dtype=bool) if season is None else seasons == season
        )
        out.append(
            {
                "season": "overall" if season is None else str(season),
                "mae_a": float(np.mean(np.abs(err_a[mask]))),
                "mae_b": float(np.mean(np.abs(err_b[mask]))),
                "delta_mae": float(np.mean(diff[mask])),
                "se": _clustered_se(diff[mask], seasons[mask], weeks[mask]),
                "rmse_a": float(np.sqrt(np.mean(err_a[mask] ** 2))),
                "rmse_b": float(np.sqrt(np.mean(err_b[mask] ** 2))),
                "n": int(mask.sum()),
            }
        )
    return pl.DataFrame(out)


def gain_importance(result: LabResult) -> pl.DataFrame:
    """LightGBM built-in importance, averaged over folds, as a share of total.

    Cheap but biased toward many-valued features, and it splits credit between
    correlated ones. Use it as a first look only.
    """
    gain = np.zeros(len(result.features))
    split = np.zeros(len(result.features))
    k = 0
    for fold in result.boosters.values():
        for booster in fold:
            g = booster.feature_importance(importance_type="gain")
            s = booster.feature_importance(importance_type="split")
            gain += g / max(g.sum(), 1e-12)
            split += s / max(s.sum(), 1e-12)
            k += 1
    return pl.DataFrame(
        {"feature": result.features, "gain_share": gain / k, "split_share": split / k}
    ).sort("gain_share", descending=True)


def shap_importance(data: LabData, result: LabResult) -> pl.DataFrame:
    """Mean |contribution| in yards per prediction, on held-out seasons.

    LightGBM's native ``pred_contrib`` (TreeSHAP); no extra dependency.
    ``mean_signed`` near 0 with a large ``mean_abs`` means the feature moves
    predictions both ways.
    """
    X_all = data.matrix(result.features)
    cat_idx = [
        j for j, name in enumerate(result.features) if name in CATEGORICAL_FEATURES
    ]
    contribs = []
    for season, fold in result.boosters.items():
        X_test = _unseen_levels_to_nan(
            X_all[result.test_rows[season]], X_all[result.train_rows[season]], cat_idx
        )
        # Contributions are additive, so the seed average explains the mean model.
        raw = np.mean(
            [np.asarray(b.predict(X_test, pred_contrib=True)) for b in fold], axis=0
        )
        contribs.append(raw[:, :-1])
    c = np.vstack(contribs)
    return pl.DataFrame(
        {
            "feature": result.features,
            "mean_abs_yards": np.mean(np.abs(c), axis=0),
            "mean_signed_yards": np.mean(c, axis=0),
        }
    ).sort("mean_abs_yards", descending=True)


def permutation_importance(
    data: LabData, result: LabResult, *, repeats: int = 3, seed: int = 0
) -> pl.DataFrame:
    """MAE increase when one feature is shuffled within each held-out season.

    No refit. ``delta_mae`` near 0 means the model is not using the feature
    out of sample; negative means it is actively hurting.
    """
    rng = np.random.default_rng(seed)
    X_all = data.matrix(result.features)
    cat_idx = [
        j for j, name in enumerate(result.features) if name in CATEGORICAL_FEATURES
    ]
    total = np.zeros(len(result.features))
    n_total = 0
    for season, fold in result.boosters.items():
        test = result.test_rows[season]
        X_test = _unseen_levels_to_nan(
            X_all[test], X_all[result.train_rows[season]], cat_idx
        )
        y = data.y[test]
        base = float(np.mean(np.abs(_predict(fold, X_test) - y)))
        for j in range(len(result.features)):
            worse = 0.0
            for _ in range(repeats):
                shuffled = X_test.copy()
                shuffled[:, j] = rng.permutation(shuffled[:, j])
                worse += float(np.mean(np.abs(_predict(fold, shuffled) - y))) - base
            total[j] += worse / repeats * test.shape[0]
        n_total += test.shape[0]
    return pl.DataFrame(
        {"feature": result.features, "delta_mae": total / n_total}
    ).sort("delta_mae", descending=True)


def ablation(
    data: LabData,
    base: Sequence[str],
    drops: Mapping[str, Sequence[str]],
    *,
    reference: LabResult | None = None,
) -> pl.DataFrame:
    """Refit without each group in ``drops``; paired MAE change vs ``base``.

    ``delta_mae`` > 0 means dropping the group hurts (the group helps).
    The slowest tool here (one full ``evaluate`` per group) and the most
    trustworthy, because the model can re-route around the missing inputs.
    """
    ref = reference or evaluate(data, base)
    out = []
    for label, group in drops.items():
        kept = [name for name in base if name not in set(group)]
        if len(kept) == len(base):
            continue
        overall = compare(data, ref, evaluate(data, kept)).filter(
            pl.col("season") == "overall"
        )
        row = overall.row(0, named=True)
        out.append(
            {
                "dropped": label,
                "n_features": len(kept),
                "delta_mae": row["delta_mae"],
                "se": row["se"],
                "mae_without": row["mae_b"],
            }
        )
    return pl.DataFrame(out).sort("delta_mae", descending=True)


def redundancy(
    data: LabData, features: Sequence[str], *, threshold: float = 0.8
) -> pl.DataFrame:
    """Numeric feature pairs whose correlation magnitude is at least ``threshold``.

    Computed on rows where both are known. Highly correlated pairs are
    candidates to drop one of; confirm with ``ablation`` before dropping.
    """
    numeric = [name for name in features if name not in CATEGORICAL_FEATURES]
    out = []
    for i, a in enumerate(numeric):
        for b in numeric[i + 1 :]:
            x, y = data.columns[a], data.columns[b]
            both = ~np.isnan(x) & ~np.isnan(y)
            if both.sum() < 50 or np.std(x[both]) == 0 or np.std(y[both]) == 0:
                continue
            r = float(np.corrcoef(x[both], y[both])[0, 1])
            if abs(r) >= threshold:
                out.append({"a": a, "b": b, "corr": r, "n": int(both.sum())})
    if not out:
        return pl.DataFrame(schema={"a": str, "b": str, "corr": float, "n": int})
    return pl.DataFrame(out).sort(pl.col("corr").abs(), descending=True)


def coverage(data: LabData, features: Sequence[str]) -> pl.DataFrame:
    """Share of rows where each feature is Unknown (NaN)."""
    return pl.DataFrame(
        {
            "feature": list(features),
            "unknown_share": [
                float(np.isnan(data.columns[n]).mean()) for n in features
            ],
        }
    ).sort("unknown_share", descending=True)


def calibration(data: LabData, result: LabResult, *, bins: int = 10) -> pl.DataFrame:
    """Mean predicted vs mean actual by predicted-value decile."""
    y = data.y[result.rows]
    order = np.argsort(result.y_hat)
    out = []
    for k, chunk in enumerate(np.array_split(order, bins)):
        err = result.y_hat[chunk] - y[chunk]
        out.append(
            {
                "decile": k + 1,
                "mean_pred": float(result.y_hat[chunk].mean()),
                "mean_actual": float(y[chunk].mean()),
                "mae": float(np.mean(np.abs(err))),
                "n": int(chunk.shape[0]),
            }
        )
    return pl.DataFrame(out)


def error_by_week(data: LabData, result: LabResult) -> pl.DataFrame:
    """Model vs season-to-date baseline MAE by point in the season."""
    y = data.y[result.rows]
    week = data.week[result.rows]
    base = data.baseline_std[result.rows]
    buckets = (("1", 1, 1), ("2-4", 2, 4), ("5-9", 5, 9), ("10+", 10, 99))
    out = []
    for label, lo, hi in buckets:
        mask = (week >= lo) & (week <= hi)
        known = mask & ~np.isnan(base)
        out.append(
            {
                "weeks": label,
                "mae_model": float(np.mean(np.abs(result.y_hat[mask] - y[mask]))),
                "mae_baseline_std": float(np.mean(np.abs(base[known] - y[known])))
                if known.any()
                else None,
                "n": int(mask.sum()),
            }
        )
    return pl.DataFrame(out)


def _predict(
    boosters: Sequence[lightgbm.Booster], X: NDArray[np.float64]
) -> NDArray[np.float64]:
    return np.mean([np.asarray(b.predict(X)) for b in boosters], axis=0)


def _unseen_levels_to_nan(
    X: NDArray[np.float64], X_train: NDArray[np.float64], cat_idx: Sequence[int]
) -> NDArray[np.float64]:
    """A category level absent from the training fold is missing, as in prod."""
    if not cat_idx:
        return X
    X = X.copy()
    for j in cat_idx:
        seen = np.unique(X_train[:, j][~np.isnan(X_train[:, j])])
        X[~np.isin(X[:, j], seen), j] = np.nan
    return X


def _clustered_se(
    d: NDArray[np.float64], seasons: NDArray[np.int64], weeks: NDArray[np.int64]
) -> float:
    n = d.shape[0]
    if n == 0:
        return float("nan")
    resid = d - d.mean()
    clusters = seasons * 100 + weeks
    sums = np.bincount(np.unique(clusters, return_inverse=True)[1], weights=resid)
    return float(np.sqrt(np.sum(sums**2)) / n)


def _nan_array(values: Sequence[float | None]) -> NDArray[np.float64]:
    return np.array([np.nan if v is None else v for v in values], dtype=np.float64)
