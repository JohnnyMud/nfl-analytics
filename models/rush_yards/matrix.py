"""Build X / y from RushRbV1 rows. Unknown → NaN. Categories from train only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from features.rush_yards import RushRbV1
from features.types import Known, Unknown

FEATURE_NAMES: tuple[str, ...] = tuple(
    name
    for name in RushRbV1.model_fields
    if name not in {"feature_set_version", "gsis_id", "game_id", "as_of"}
)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "roof",
    "surface",
    "report_status",
    "practice_status",
)

# Unused integer code reserved for missing / unseen levels. The matrix still
# writes NaN so boosters take their native missing path; this code is never
# emitted as a dummy column.
MISSING_CATEGORY_CODE = -1


@dataclass(frozen=True, slots=True)
class CategoryEncoder:
    """Integer codes for categorical levels observed in the training window."""

    levels: dict[str, tuple[str, ...]]

    def code(self, name: str, value: str | None) -> float:
        if value is None:
            return np.nan
        try:
            return float(self.levels.get(name, ()).index(value))
        except ValueError:
            return np.nan


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    X: NDArray[np.float64]
    y: NDArray[np.float64] | None
    feature_names: tuple[str, ...]
    categorical_indices: tuple[int, ...]
    encoder: CategoryEncoder


def fit_category_encoder(rows: Sequence[RushRbV1]) -> CategoryEncoder:
    """Collect category levels in first-seen order from ``rows`` only."""
    ordered: dict[str, list[str]] = {name: [] for name in CATEGORICAL_FEATURES}
    seen: dict[str, set[str]] = {name: set() for name in CATEGORICAL_FEATURES}
    for row in rows:
        for name in CATEGORICAL_FEATURES:
            value = getattr(row, name)
            if not isinstance(value, Known):
                continue
            level = value.value
            if not isinstance(level, str):
                raise TypeError(f"{name} Known value must be str, got {type(level)!r}")
            if level not in seen[name]:
                seen[name].add(level)
                ordered[name].append(level)
    return CategoryEncoder(levels={name: tuple(vals) for name, vals in ordered.items()})


def build_matrix(
    rows: Sequence[RushRbV1],
    *,
    y: Sequence[float] | None = None,
    encoder: CategoryEncoder | None = None,
) -> FeatureMatrix:
    """Stack feature rows. ``encoder`` must come from the training window.

    Unknown and a test-week category not seen in training become NaN, never 0
    and never a new dummy column.
    """
    if encoder is None:
        encoder = fit_category_encoder(rows)
    if y is not None and len(y) != len(rows):
        raise ValueError("y length must match the number of feature rows")

    n = len(rows)
    p = len(FEATURE_NAMES)
    X = np.full((n, p), np.nan, dtype=np.float64)
    cat_index = {name: i for i, name in enumerate(FEATURE_NAMES)}
    categorical_indices = tuple(cat_index[name] for name in CATEGORICAL_FEATURES)

    for i, row in enumerate(rows):
        for j, name in enumerate(FEATURE_NAMES):
            X[i, j] = _cell(getattr(row, name), name, encoder)

    y_arr: NDArray[np.float64] | None = None
    if y is not None:
        y_arr = np.asarray(list(y), dtype=np.float64)

    return FeatureMatrix(
        X=X,
        y=y_arr,
        feature_names=FEATURE_NAMES,
        categorical_indices=categorical_indices,
        encoder=encoder,
    )


def _cell(
    value: Known[object] | Unknown,
    name: str,
    encoder: CategoryEncoder,
) -> float:
    if isinstance(value, Unknown):
        return np.nan
    if not isinstance(value, Known):
        raise TypeError(f"{name} is neither Known nor Unknown: {type(value)!r}")
    raw = value.value
    if name in CATEGORICAL_FEATURES:
        if not isinstance(raw, str):
            raise TypeError(f"{name} Known value must be str, got {type(raw)!r}")
        return encoder.code(name, raw)
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, int | float):
        return float(raw)
    raise TypeError(f"{name} Known value is not numeric: {type(raw)!r}")
