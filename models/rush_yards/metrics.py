"""MAE and RMSE on rows where y_hat is not None. No sklearn."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricStats:
    mae: float
    rmse: float
    n: int
    n_unknown: int


def compute_metrics(
    y_true: Sequence[float], y_hat: Sequence[float | None]
) -> MetricStats:
    """MAE / RMSE over known predictions. Unknowns increment ``n_unknown`` only.

    When every prediction is Unknown, ``n`` is 0 and MAE/RMSE are 0.0 so the
    stored metric row can remain NOT NULL without inventing a filled y_hat.
    """
    if len(y_true) != len(y_hat):
        raise ValueError("y_true and y_hat must have the same length")

    abs_err: list[float] = []
    sq_err: list[float] = []
    n_unknown = 0
    for target, pred in zip(y_true, y_hat, strict=True):
        if pred is None:
            n_unknown += 1
            continue
        err = target - pred
        abs_err.append(abs(err))
        sq_err.append(err * err)

    n = len(abs_err)
    if n == 0:
        return MetricStats(mae=0.0, rmse=0.0, n=0, n_unknown=n_unknown)
    return MetricStats(
        mae=sum(abs_err) / n,
        rmse=math.sqrt(sum(sq_err) / n),
        n=n,
        n_unknown=n_unknown,
    )
