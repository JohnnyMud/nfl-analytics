"""Predictions are read from model.prediction; unknown and unplayed stay null."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.api.helpers import (
    insert_game,
    insert_player,
    insert_player_stat,
    insert_team,
)

RB = "00-0038134"
KICK_1 = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)
KICK_2 = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)
PREDICTED_AT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _seed(session: Session) -> None:
    for abbr, name in (("KC", "Chiefs"), ("DEN", "Broncos")):
        insert_team(
            session,
            team_abbr=abbr,
            team_name=name,
            team_nick=name,
            team_conf="AFC",
            team_division="AFC West",
        )
    insert_player(session, gsis_id=RB, display_name="Test Back", latest_team="KC")
    played = insert_game(
        session,
        game_id="2026_01_DEN_KC",
        season=2026,
        week=1,
        home_team="KC",
        away_team="DEN",
        kickoff_at=KICK_1,
    )
    insert_game(
        session,
        game_id="2026_02_KC_DEN",
        season=2026,
        week=2,
        home_team="DEN",
        away_team="KC",
        kickoff_at=KICK_2,
    )
    insert_player_stat(
        session,
        gsis_id=RB,
        game=played,
        team="KC",
        opponent_team="DEN",
        rushing_yards=71,
    )


def _predict(
    engine: Engine,
    *,
    run_id: UUID,
    model_name: str,
    model_version: str,
    game_id: str,
    as_of: datetime,
    y_hat: float | None,
    y_true: float | None = None,
    predicted_at: datetime = PREDICTED_AT,
) -> None:
    with engine.begin() as conn:
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
                "model_version": model_version,
                "gsis_id": RB,
                "game_id": game_id,
                "as_of": as_of,
                "y_hat": y_hat,
                "y_true": y_true,
                "predicted_at": predicted_at,
            },
        )


def test_predictions_unknown_player_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/players/00-0000000/predictions")
    assert response.status_code == 404
    assert response.json() == {"detail": "player not found"}


def test_predictions_empty_when_no_run_scored_player(
    api_client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        _seed(session)

    response = api_client.get(f"/api/players/{RB}/predictions")
    assert response.status_code == 200
    assert response.json() == []


def test_predictions_carry_provenance_and_keep_nulls(
    api_client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        _seed(session)
    run_id = uuid4()
    _predict(
        migrated_engine,
        run_id=run_id,
        model_name="xgboost",
        model_version="xgb_rush_rb_v1+pregame_safe",
        game_id="2026_01_DEN_KC",
        as_of=KICK_1,
        y_hat=64.5,
        y_true=71.0,
    )
    _predict(
        migrated_engine,
        run_id=run_id,
        model_name="baseline_std",
        model_version="baseline_std_v1",
        game_id="2026_01_DEN_KC",
        as_of=KICK_1,
        y_hat=None,
        y_true=71.0,
    )
    _predict(
        migrated_engine,
        run_id=run_id,
        model_name="xgboost",
        model_version="xgb_rush_rb_v1+pregame_safe",
        game_id="2026_02_KC_DEN",
        as_of=KICK_2,
        y_hat=58.0,
    )

    rows = api_client.get(f"/api/players/{RB}/predictions").json()

    assert [(row["week"], row["model_name"]) for row in rows] == [
        (2, "xgboost"),
        (1, "baseline_std"),
        (1, "xgboost"),
    ]
    upcoming, unknown, scored = rows
    assert upcoming["y_true"] is None
    assert upcoming["actual_rushing_yards"] is None
    assert unknown["y_hat"] is None
    assert unknown["actual_rushing_yards"] == 71
    assert scored["run_id"] == str(run_id)
    assert scored["model_version"] == "xgb_rush_rb_v1+pregame_safe"
    assert scored["feature_set_version"] == "rush_rb_v1"
    assert scored["home_team"] == "KC"
    assert scored["y_true"] == 71.0


def test_newest_run_wins_per_game_and_model_version(
    api_client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        _seed(session)
    old_run, new_run, full_run = uuid4(), uuid4(), uuid4()
    for run_id, y_hat, predicted_at in (
        (old_run, 50.0, PREDICTED_AT - timedelta(days=1)),
        (new_run, 60.0, PREDICTED_AT),
    ):
        _predict(
            migrated_engine,
            run_id=run_id,
            model_name="xgboost",
            model_version="xgb_rush_rb_v1+pregame_safe",
            game_id="2026_01_DEN_KC",
            as_of=KICK_1,
            y_hat=y_hat,
            predicted_at=predicted_at,
        )
    # prediction_pkey is (run_id, model_name, gsis_id, game_id). A second
    # version of the same model is a different run, matching walk-forward.
    _predict(
        migrated_engine,
        run_id=full_run,
        model_name="xgboost",
        model_version="xgb_rush_rb_v1+full",
        game_id="2026_01_DEN_KC",
        as_of=KICK_1,
        y_hat=55.0,
        predicted_at=PREDICTED_AT - timedelta(days=1),
    )

    rows = api_client.get(f"/api/players/{RB}/predictions").json()

    by_version = {row["model_version"]: row for row in rows}
    assert len(rows) == 2
    assert by_version["xgb_rush_rb_v1+pregame_safe"]["run_id"] == str(new_run)
    assert by_version["xgb_rush_rb_v1+pregame_safe"]["y_hat"] == 60.0
    assert by_version["xgb_rush_rb_v1+full"]["y_hat"] == 55.0


def test_predictions_season_filter(
    api_client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        _seed(session)
    _predict(
        migrated_engine,
        run_id=uuid4(),
        model_name="xgboost",
        model_version="xgb_rush_rb_v1+pregame_safe",
        game_id="2026_01_DEN_KC",
        as_of=KICK_1,
        y_hat=64.5,
    )

    assert api_client.get(f"/api/players/{RB}/predictions?season=2025").json() == []
    assert len(api_client.get(f"/api/players/{RB}/predictions?season=2026").json()) == 1
