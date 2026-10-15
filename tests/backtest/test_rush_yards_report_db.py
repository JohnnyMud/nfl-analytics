"""The report reads stored rows; unlabeled runs are scored live, never as zero."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from backtest.rush_yards_report import list_runs, load_report
from tests.api.helpers import (
    insert_game,
    insert_player,
    insert_player_stat,
    insert_team,
)

PREDICTED_AT = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)
KICK_1 = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)
KICK_2 = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)
RB = "00-0077001"

# Helpers commit each row, so a failed seed must still clear the shared database.
_RESET = text(
    "TRUNCATE model.prediction, model.metric, model.feature_row, "
    "nfl.player_stats, nfl.games, nfl.players, nfl.teams CASCADE"
)


def _reset(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(_RESET)


@pytest.fixture
def seeded(migrated_engine: Engine) -> Iterator[Engine]:
    _reset(migrated_engine)
    try:
        with Session(migrated_engine) as session:
            for abbr in ("KC", "BUF"):
                insert_team(
                    session,
                    team_abbr=abbr,
                    team_name=abbr,
                    team_nick=abbr,
                    team_conf="AFC",
                    team_division="AFC East",
                )
            insert_player(
                session,
                gsis_id=RB,
                display_name="Report Back",
                latest_team="KC",
                position="RB",
            )
            game_1 = insert_game(
                session,
                game_id="2026_01_BUF_KC",
                season=2026,
                week=1,
                home_team="KC",
                away_team="BUF",
                kickoff_at=KICK_1,
            )
            insert_game(
                session,
                game_id="2026_02_KC_BUF",
                season=2026,
                week=2,
                home_team="BUF",
                away_team="KC",
                kickoff_at=KICK_2,
            )
            insert_player_stat(
                session,
                gsis_id=RB,
                game=game_1,
                team="KC",
                opponent_team="BUF",
                rushing_yards=50,
            )
        yield migrated_engine
    finally:
        _reset(migrated_engine)


def _predict(
    conn: Connection,
    run_id: UUID,
    model_name: str,
    game_id: str,
    as_of: datetime,
    y_hat: float | None,
    y_true: float | None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO model.prediction (
                run_id, model_name, model_version, feature_set_version,
                gsis_id, game_id, as_of, y_hat, y_true, predicted_at
            )
            VALUES (
                :run_id, :model_name, :model_version, 'rush_rb_v1',
                :gsis_id, :game_id, :as_of, :y_hat, :y_true, :predicted_at
            )
            """
        ),
        {
            "run_id": run_id,
            "model_name": model_name,
            "model_version": f"{model_name}_v1",
            "gsis_id": RB,
            "game_id": game_id,
            "as_of": as_of,
            "y_hat": y_hat,
            "y_true": y_true,
            "predicted_at": PREDICTED_AT,
        },
    )


def test_stored_metrics_are_reported_as_stored_not_recomputed(
    seeded: Engine,
) -> None:
    run_id = uuid4()
    with seeded.begin() as conn:
        _predict(conn, run_id, "xgboost", "2026_01_BUF_KC", KICK_1, 40.0, 50.0)
        conn.execute(
            text(
                """
                INSERT INTO model.metric
                    (run_id, model_name, season, mae, rmse, n, n_unknown)
                VALUES (:run_id, 'xgboost', NULL, 99.0, 99.0, 1, 0)
                """
            ),
            {"run_id": run_id},
        )

    with seeded.connect() as conn:
        report = load_report(conn, [run_id])
        runs = list_runs(conn)

    assert [run.run_id for run in runs] == [run_id]
    assert runs[0].has_metrics
    (line,) = report.metrics
    assert line.source == "stored"
    assert line.mae == 99.0
    assert line.model_version == "xgboost_v1"


def test_live_scoring_separates_unknown_and_unlabeled(seeded: Engine) -> None:
    run_id = uuid4()
    with seeded.begin() as conn:
        _predict(conn, run_id, "xgboost", "2026_01_BUF_KC", KICK_1, 40.0, None)
        _predict(conn, run_id, "baseline_std", "2026_01_BUF_KC", KICK_1, None, None)
        _predict(conn, run_id, "xgboost", "2026_02_KC_BUF", KICK_2, 60.0, None)

    with seeded.connect() as conn:
        report = load_report(conn, [run_id])

    overall = {m.model_name: m for m in report.metrics if m.season is None}
    assert overall["xgboost"].source == "live"
    assert overall["xgboost"].mae == pytest.approx(10.0)
    assert overall["xgboost"].n == 1
    assert overall["xgboost"].n_unlabeled == 1
    assert overall["baseline_std"].mae is None
    assert overall["baseline_std"].n_unknown == 1
    assert overall["baseline_std"].n == 0


def test_common_rows_drop_games_any_model_left_unknown(seeded: Engine) -> None:
    run_id = uuid4()
    with seeded.begin() as conn:
        _predict(conn, run_id, "xgboost", "2026_01_BUF_KC", KICK_1, 40.0, 50.0)
        _predict(conn, run_id, "baseline_std", "2026_01_BUF_KC", KICK_1, 45.0, 50.0)
        _predict(conn, run_id, "xgboost", "2026_02_KC_BUF", KICK_2, 60.0, 70.0)
        _predict(conn, run_id, "baseline_std", "2026_02_KC_BUF", KICK_2, None, 70.0)

    with seeded.connect() as conn:
        report = load_report(conn, [run_id])

    by_model = {line.model_name: line for line in report.common}
    assert by_model["xgboost"].n == 1
    assert by_model["xgboost"].mae == pytest.approx(10.0)
    assert by_model["baseline_std"].mae == pytest.approx(5.0)


def test_unknown_run_id_raises(seeded: Engine) -> None:
    with seeded.connect() as conn, pytest.raises(LookupError):
        load_report(conn, [uuid4()])
