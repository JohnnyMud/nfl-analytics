"""Report stored rush_rb runs from ``model.*``. Never re-predicts.

``python -m backtest.rush_yards_report``               list stored runs
``python -m backtest.rush_yards_report RUN_ID [...]``  report those runs

A run with ``model.metric`` rows reports them as stored: those labels were
frozen when the run was written. A run without metric rows (predict-upcoming)
is scored live against current ``nfl.player_stats``; a prediction whose game
has no box-score row yet is counted as unlabeled, never as zero.

The common-row table rescores every (run, model) on only the player-games
where all of them produced a prediction and a label exists, so a baseline's
``Unknown`` rows cannot flatter or penalise it relative to the boosters.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from common.settings import get_settings


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunSummary(_Frozen):
    run_id: UUID
    predicted_at: datetime
    model_versions: str
    feature_set_version: str
    first_season: int
    last_season: int
    n_predictions: int
    n_labeled: int
    has_metrics: bool


class MetricLine(_Frozen):
    run_id: UUID
    model_name: str
    model_version: str
    season: int | None
    mae: float | None
    rmse: float | None
    n: int
    n_unknown: int
    n_unlabeled: int
    source: Literal["stored", "live"]


class CommonLine(_Frozen):
    run_id: UUID
    model_name: str
    model_version: str
    mae: float
    rmse: float
    n: int


class RushReport(_Frozen):
    runs: list[RunSummary]
    metrics: list[MetricLine]
    common: list[CommonLine]


_RUNS_SQL = text(
    """
    SELECT p.run_id,
           max(p.predicted_at) AS predicted_at,
           string_agg(DISTINCT p.model_version, ', ') AS model_versions,
           string_agg(DISTINCT p.feature_set_version, ', ') AS feature_set_version,
           min(g.season) AS first_season,
           max(g.season) AS last_season,
           count(*) AS n_predictions,
           count(p.y_true) AS n_labeled,
           EXISTS (
               SELECT 1 FROM model.metric AS m WHERE m.run_id = p.run_id
           ) AS has_metrics
    FROM model.prediction AS p
    JOIN nfl.games AS g ON g.game_id = p.game_id
    WHERE CAST(:runs AS uuid[]) IS NULL OR p.run_id = ANY(CAST(:runs AS uuid[]))
    GROUP BY p.run_id
    ORDER BY max(p.predicted_at) DESC
    """
)

_STORED_METRICS_SQL = text(
    """
    SELECT m.run_id, m.model_name, v.model_version, m.season,
           m.mae, m.rmse, m.n, m.n_unknown
    FROM model.metric AS m
    JOIN (
        SELECT DISTINCT run_id, model_name, model_version
        FROM model.prediction
        WHERE run_id = ANY(CAST(:runs AS uuid[]))
    ) AS v USING (run_id, model_name)
    WHERE m.run_id = ANY(CAST(:runs AS uuid[]))
    """
)

_LIVE_METRICS_SQL = text(
    """
    WITH scored AS (
        SELECT p.run_id, p.model_name, p.model_version, g.season, p.y_hat,
               CAST(s.rushing_yards AS double precision) AS y
        FROM model.prediction AS p
        JOIN nfl.games AS g ON g.game_id = p.game_id
        LEFT JOIN nfl.player_stats AS s
          ON s.gsis_id = p.gsis_id AND s.game_id = p.game_id
        WHERE p.run_id = ANY(CAST(:runs AS uuid[]))
    )
    SELECT run_id, model_name, model_version,
           CASE WHEN GROUPING(season) = 1 THEN NULL ELSE season END AS season,
           avg(abs(y_hat - y)) AS mae,
           sqrt(avg(power(y_hat - y, 2))) AS rmse,
           count(*) FILTER (WHERE y_hat IS NOT NULL AND y IS NOT NULL) AS n,
           count(*) FILTER (WHERE y_hat IS NULL AND y IS NOT NULL) AS n_unknown,
           count(*) FILTER (WHERE y IS NULL) AS n_unlabeled
    FROM scored
    GROUP BY GROUPING SETS (
        (run_id, model_name, model_version, season),
        (run_id, model_name, model_version)
    )
    """
)

_COMMON_SQL = text(
    """
    WITH labeled AS (
        SELECT p.run_id, p.model_name, p.model_version, p.gsis_id, p.game_id,
               p.y_hat,
               COALESCE(p.y_true, CAST(s.rushing_yards AS double precision)) AS y
        FROM model.prediction AS p
        LEFT JOIN nfl.player_stats AS s
          ON s.gsis_id = p.gsis_id AND s.game_id = p.game_id
        WHERE p.run_id = ANY(CAST(:runs AS uuid[]))
    ),
    arms AS (
        SELECT count(DISTINCT run_id::text || '/' || model_name) AS k FROM labeled
    ),
    common AS (
        SELECT gsis_id, game_id
        FROM labeled
        WHERE y_hat IS NOT NULL AND y IS NOT NULL
        GROUP BY gsis_id, game_id
        HAVING count(DISTINCT run_id::text || '/' || model_name)
               = (SELECT k FROM arms)
    )
    SELECT l.run_id, l.model_name, l.model_version,
           avg(abs(l.y_hat - l.y)) AS mae,
           sqrt(avg(power(l.y_hat - l.y, 2))) AS rmse,
           count(*) AS n
    FROM labeled AS l
    JOIN common AS c ON c.gsis_id = l.gsis_id AND c.game_id = l.game_id
    GROUP BY l.run_id, l.model_name, l.model_version
    """
)


def list_runs(conn: Connection) -> list[RunSummary]:
    return [
        RunSummary.model_validate(row._mapping)
        for row in conn.execute(_RUNS_SQL, {"runs": None})
    ]


def load_report(conn: Connection, run_ids: Sequence[UUID]) -> RushReport:
    """Read stored rows for ``run_ids``. Raises if any run id is not stored."""
    if not run_ids:
        raise ValueError("need at least one run_id")
    runs_param = {"runs": [str(run_id) for run_id in run_ids]}
    runs = [
        RunSummary.model_validate(row._mapping)
        for row in conn.execute(_RUNS_SQL, runs_param)
    ]
    missing = set(run_ids) - {run.run_id for run in runs}
    if missing:
        absent = ", ".join(sorted(map(str, missing)))
        raise LookupError(f"no stored predictions for run(s): {absent}")

    stored = [run.run_id for run in runs if run.has_metrics]
    live = [run.run_id for run in runs if not run.has_metrics]
    metrics: list[MetricLine] = []
    if stored:
        metrics += [
            MetricLine.model_validate(
                {**row._mapping, "n_unlabeled": 0, "source": "stored"}
            )
            for row in conn.execute(
                _STORED_METRICS_SQL, {"runs": [str(r) for r in stored]}
            )
        ]
    if live:
        metrics += [
            MetricLine.model_validate({**row._mapping, "source": "live"})
            for row in conn.execute(_LIVE_METRICS_SQL, {"runs": [str(r) for r in live]})
        ]
    metrics.sort(
        key=lambda m: (
            str(m.run_id),
            m.season is not None,
            m.season or 0,
            m.model_name,
        )
    )
    common = sorted(
        (
            CommonLine.model_validate(row._mapping)
            for row in conn.execute(_COMMON_SQL, runs_param)
        ),
        key=lambda line: line.rmse,
    )
    return RushReport(runs=runs, metrics=metrics, common=common)


def format_runs(runs: Sequence[RunSummary]) -> str:
    if not runs:
        return "no stored runs"
    lines = [
        f"{'run_id':36}  {'predicted_at':25}  {'seasons':9}  {'preds':>6}  "
        f"{'labeled':>7}  metrics  model_versions"
    ]
    for run in runs:
        seasons = (
            str(run.first_season)
            if run.first_season == run.last_season
            else f"{run.first_season}-{run.last_season}"
        )
        lines.append(
            f"{run.run_id!s:36}  {run.predicted_at.isoformat(timespec='seconds'):25}  "
            f"{seasons:9}  {run.n_predictions:6d}  {run.n_labeled:7d}  "
            f"{'stored' if run.has_metrics else 'live':7}  {run.model_versions}"
        )
    return "\n".join(lines)


def format_report(report: RushReport) -> str:
    out = [format_runs(report.runs), ""]
    for run in report.runs:
        lines = [m for m in report.metrics if m.run_id == run.run_id]
        source = "stored labels" if run.has_metrics else "live labels"
        out.append(f"run {run.run_id} ({source})")
        out.append(
            f"  {'season':>7}  {'model_version':32}  {'MAE':>6}  {'RMSE':>6}  "
            f"{'n':>6}  {'unknown':>7}  {'unlabeled':>9}"
        )
        for m in lines:
            season = "overall" if m.season is None else str(m.season)
            out.append(
                f"  {season:>7}  {m.model_version:32}  {_num(m.mae)}  "
                f"{_num(m.rmse)}  {m.n:6d}  {m.n_unknown:7d}  {m.n_unlabeled:9d}"
            )
        out.append("")
    if report.common:
        out.append(
            f"common rows: {report.common[0].n} player-games scored by every "
            "(run, model) above"
        )
        for line in report.common:
            out.append(
                f"  {line.model_version:32}  {str(line.run_id)[:8]}  "
                f"MAE {line.mae:6.2f}  RMSE {line.rmse:6.2f}"
            )
    else:
        out.append("common rows: none (no player-game is labeled and scored by all)")
    return "\n".join(out)


def _num(value: float | None) -> str:
    return "     -" if value is None else f"{value:6.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backtest.rush_yards_report")
    parser.add_argument("run_ids", nargs="*", type=UUID)
    args = parser.parse_args(argv)
    engine = create_engine(get_settings().sqlalchemy_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if not args.run_ids:
                sys.stdout.write(format_runs(list_runs(conn)) + "\n")
                return 0
            report = load_report(conn, args.run_ids)
    finally:
        engine.dispose()
    sys.stdout.write(format_report(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
