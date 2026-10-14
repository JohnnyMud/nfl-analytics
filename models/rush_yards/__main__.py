"""Rush yards runs against ``DATABASE_URL``.

``backtest``          walk-forward over stored seasons; writes predictions + metrics
``predict-upcoming``  one scheduled week; writes unlabeled predictions
``prune``             delete all but the newest N runs (run by hand)

Reads ``nfl.*`` in a read-only transaction, then writes one ``model.*``
transaction per run. ``--dry-run`` reads and fits but writes nothing. The
wall clock is read here, once per run, as ``predicted_at`` provenance only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from common.settings import get_settings
from features.rush_yards import build_rush_rb_v1
from features.rush_yards_source import (
    RushHistory,
    RushSnapshotIndex,
    load_rush_history,
    rb_population,
    targets_from_box_scores,
    upcoming_targets,
    week_first_kickoff,
    week_games,
)
from models.rush_yards.estimators import DEFAULT_N_ESTIMATORS
from models.rush_yards.store import prune_runs, write_run
from models.rush_yards.types import (
    FeatureSubset,
    LabeledRushRow,
    MetricRecord,
    PendingRushRow,
)
from models.rush_yards.walk_forward import predict_pending, walk_forward

TRAIN_START_DEFAULT = 2016
SCORE_START_DEFAULT = 2017
SCORE_END_DEFAULT = 2025
SUBSETS: tuple[FeatureSubset, ...] = ("pregame_safe", "full")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = create_engine(get_settings().sqlalchemy_url)
    try:
        if args.command == "backtest":
            return _backtest(engine, args)
        if args.command == "predict-upcoming":
            return _predict_upcoming(engine, args)
        return _prune(engine, args)
    finally:
        engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m models.rush_yards")
    sub = parser.add_subparsers(dest="command", required=True)

    backtest = sub.add_parser("backtest", help="walk-forward over stored seasons")
    backtest.add_argument("--train-start", type=int, default=TRAIN_START_DEFAULT)
    backtest.add_argument("--score-start", type=int, default=SCORE_START_DEFAULT)
    backtest.add_argument("--score-end", type=int, default=SCORE_END_DEFAULT)
    _common(backtest, default_subset="pregame_safe")

    upcoming = sub.add_parser("predict-upcoming", help="predict one scheduled week")
    upcoming.add_argument("--season", type=int, required=True)
    upcoming.add_argument("--week", type=int, required=True)
    upcoming.add_argument("--train-start", type=int, default=TRAIN_START_DEFAULT)
    _common(upcoming, default_subset="pregame_safe")

    prune = sub.add_parser("prune", help="delete all but the newest N runs")
    prune.add_argument("--keep", type=int, required=True)
    prune.add_argument("--dry-run", action="store_true")
    return parser


def _common(parser: argparse.ArgumentParser, *, default_subset: str) -> None:
    parser.add_argument("--subset", choices=SUBSETS, default=default_subset)
    parser.add_argument("--n-estimators", type=int, default=DEFAULT_N_ESTIMATORS)
    parser.add_argument("--dry-run", action="store_true")


def _read_history(
    engine: Engine, *, season_start: int, season_end: int, kickoff_before: datetime
) -> RushHistory:
    with engine.connect() as conn:
        _read_only(conn)
        return load_rush_history(
            conn,
            season_start=season_start,
            season_end=season_end,
            kickoff_before=kickoff_before,
        )


def _read_only(conn: Connection) -> None:
    conn.execute(text("SET TRANSACTION READ ONLY"))


def _labeled_rows(
    history: RushHistory, *, season_start: int, season_end: int
) -> list[LabeledRushRow]:
    index = RushSnapshotIndex(history)
    population = rb_population(
        history, season_start=season_start, season_end=season_end
    )
    rows: list[LabeledRushRow] = []
    for box, target in zip(
        population, targets_from_box_scores(population), strict=True
    ):
        rows.append(
            LabeledRushRow(
                gsis_id=box.gsis_id,
                game_id=box.game_id,
                season=box.season,
                week=box.week,
                kickoff_at=box.kickoff_at,
                y_true=float(box.rushing_yards),
                features=build_rush_rb_v1(
                    target.gsis_id, target.as_of, index.snapshot(target)
                ),
            )
        )
    return rows


def _backtest(engine: Engine, args: argparse.Namespace) -> int:
    if not args.train_start <= args.score_start <= args.score_end:
        raise SystemExit("need train-start <= score-start <= score-end")
    predicted_at = datetime.now(UTC)
    subset = cast(FeatureSubset, args.subset)
    # Every season's Super Bowl is played before March 1 of the next year.
    kickoff_before = datetime(args.score_end + 1, 3, 1, tzinfo=UTC)
    history = _read_history(
        engine,
        season_start=args.train_start,
        season_end=args.score_end,
        kickoff_before=kickoff_before,
    )
    rows = _labeled_rows(
        history, season_start=args.train_start, season_end=args.score_end
    )
    _say(f"labeled RB games {args.train_start}-{args.score_end}: {len(rows)}")
    result = walk_forward(
        rows,
        predicted_at=predicted_at,
        score_start=args.score_start,
        score_end=args.score_end,
        feature_subset=subset,
        n_estimators=args.n_estimators,
    )
    _say(f"run_id={result.run_id} subset={subset} folds={len(result.folds)}")
    _print_metrics(result.metrics)

    if args.dry_run:
        _say("dry run: nothing written")
        return 0
    scored = {(pred.gsis_id, pred.game_id) for pred in result.predictions}
    features = [row.features for row in rows if (row.gsis_id, row.game_id) in scored]
    with engine.begin() as conn:
        summary = write_run(
            conn,
            run_id=result.run_id,
            features=features,
            predictions=result.predictions,
            metrics=result.metrics,
            built_at=predicted_at,
        )
    _say(
        f"wrote run {summary.run_id}: {summary.predictions} predictions, "
        f"{summary.metrics} metrics, {summary.feature_rows_inserted} new feature "
        f"rows ({summary.feature_rows_already_stored} already stored)"
    )
    return 0


def _predict_upcoming(engine: Engine, args: argparse.Namespace) -> int:
    predicted_at = datetime.now(UTC)
    subset = cast(FeatureSubset, args.subset)
    with engine.connect() as conn:
        _read_only(conn)
        cutoff = week_first_kickoff(conn, season=args.season, week=args.week)
    if cutoff is None:
        raise SystemExit(f"no REG games scheduled for {args.season} week {args.week}")
    history = _read_history(
        engine,
        season_start=args.train_start,
        season_end=args.season,
        kickoff_before=cutoff,
    )
    games = week_games(history, season=args.season, week=args.week)
    targets = upcoming_targets(history, games)
    clubs = {game.home_team for game in games} | {game.away_team for game in games}
    covered = {target.team for target in targets}
    _say(
        f"{args.season} week {args.week}: data cutoff {cutoff.isoformat()}, "
        f"{len(targets)} RB targets, clubs without a prior game this season: "
        f"{sorted(clubs - covered) or 'none'}"
    )
    if not targets:
        raise SystemExit("no targets: every club lacks a prior game this season")

    index = RushSnapshotIndex(history)
    games_by_id = {game.game_id: game for game in games}
    pending = [
        PendingRushRow(
            gsis_id=target.gsis_id,
            game_id=target.game_id,
            season=games_by_id[target.game_id].season,
            week=games_by_id[target.game_id].week,
            kickoff_at=target.as_of,
            features=build_rush_rb_v1(
                target.gsis_id, target.as_of, index.snapshot(target)
            ),
        )
        for target in targets
    ]
    labeled = _labeled_rows(
        history, season_start=args.train_start, season_end=args.season
    )
    predictions = predict_pending(
        labeled,
        pending,
        predicted_at=predicted_at,
        feature_subset=subset,
        n_estimators=args.n_estimators,
    )
    run_id = predictions[0].run_id
    _say(f"run_id={run_id} subset={subset} predictions={len(predictions)}")
    if args.dry_run:
        _say("dry run: nothing written")
        return 0
    with engine.begin() as conn:
        summary = write_run(
            conn,
            run_id=run_id,
            features=[row.features for row in pending],
            predictions=predictions,
            metrics=(),
            built_at=predicted_at,
        )
    _say(f"wrote run {summary.run_id}: {summary.predictions} predictions")
    return 0


def _prune(engine: Engine, args: argparse.Namespace) -> int:
    with engine.begin() as conn:
        summary = prune_runs(conn, keep=args.keep, dry_run=args.dry_run)
    verb = "would delete" if args.dry_run else "deleted"
    _say(
        f"kept {len(summary.kept_runs)} runs; {verb} {len(summary.deleted_runs)} "
        f"runs ({summary.predictions_deleted} predictions, "
        f"{summary.metrics_deleted} metrics, "
        f"{summary.feature_rows_deleted} feature rows)"
    )
    return 0


def _print_metrics(metrics: Sequence[MetricRecord]) -> None:
    for metric in sorted(
        metrics, key=lambda m: (m.season if m.season is not None else 0, m.model_name)
    ):
        season = "overall" if metric.season is None else str(metric.season)
        _say(
            f"  {season:>7} {metric.model_name:<15} MAE {metric.mae:6.2f} "
            f"RMSE {metric.rmse:6.2f} n={metric.n} unknown={metric.n_unknown}"
        )


def _say(message: str) -> None:
    sys.stdout.write(message + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
