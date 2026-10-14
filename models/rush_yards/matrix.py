"""Build X / y from RushRbV1 rows. Unknown → NaN. Categories from train only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from features.rush_yards import RushRbV1
from features.types import Known, Unknown
from models.rush_yards.types import FeatureSubset

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

# Not verifiably known before kickoff: temp/wind are game-day actuals; injury
# reports are week files with no publish time; pre-2025 depth snapshots carry
# a derived instant (the club kickoff), not a publication time.
NOT_PREGAME_VERIFIED: frozenset[str] = frozenset(
    {"temp", "wind", "report_status", "practice_status", "depth_team"}
)

FEATURE_SUBSETS: dict[FeatureSubset, tuple[str, ...]] = {
    "full": FEATURE_NAMES,
    "pregame_safe": tuple(
        name for name in FEATURE_NAMES if name not in NOT_PREGAME_VERIFIED
    ),
}

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
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> FeatureMatrix:
    """Stack feature rows. ``encoder`` must come from the training window.

    Unknown and a test-week category not seen in training become NaN, never 0
    and never a new dummy column. ``feature_names`` selects registry columns;
    a name outside the registry is an error, not a silent extra column.
    """
    unregistered = [name for name in feature_names if name not in FEATURE_NAMES]
    if unregistered:
        raise ValueError(f"unregistered features: {unregistered}")
    if encoder is None:
        encoder = fit_category_encoder(rows)
    if y is not None and len(y) != len(rows):
        raise ValueError("y length must match the number of feature rows")

    names = tuple(feature_names)
    n = len(rows)
    p = len(names)
    X = np.full((n, p), np.nan, dtype=np.float64)
    categorical_indices = tuple(
        i for i, name in enumerate(names) if name in CATEGORICAL_FEATURES
    )

    for i, row in enumerate(rows):
        for j, name in enumerate(names):
            X[i, j] = _cell(getattr(row, name), name, encoder)

    y_arr: NDArray[np.float64] | None = None
    if y is not None:
        y_arr = np.asarray(list(y), dtype=np.float64)

    return FeatureMatrix(
        X=X,
        y=y_arr,
        feature_names=names,
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
