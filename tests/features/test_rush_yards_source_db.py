"""load_rush_history bounds every fact by kickoff_before in SQL."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from features.rush_yards_source import load_rush_history
from infra.models import DepthChart, Game, Player, PlayerStat, Team

INGESTED_AT = datetime(2026, 10, 1, tzinfo=UTC)
KICK_1 = datetime(2019, 9, 8, 17, 0, tzinfo=UTC)
KICK_2 = datetime(2019, 9, 15, 17, 0, tzinfo=UTC)
RB = "00-0060001"
WR = "00-0060002"


@pytest.fixture
def seeded(migrated_engine: Engine) -> Iterator[Engine]:
    with Session(migrated_engine) as session:
        for abbr, franchise in (("OAK", "F-LV"), ("LV", "F-LV"), ("KC", "F-KC")):
            session.add(
                Team(
                    team_abbr=abbr,
                    franchise_id=franchise,
                    team_name=abbr,
                    team_nick=abbr,
                    team_conf="AFC",
                    team_division="AFC West",
                    ingested_at=INGESTED_AT,
                )
            )
        session.flush()
        for gsis_id in (RB, WR):
            session.add(
                Player(gsis_id=gsis_id, display_name=gsis_id, ingested_at=INGESTED_AT)
            )
        for week, kick in ((1, KICK_1), (2, KICK_2)):
            session.add(
                Game(
                    game_id=f"2019_0{week}_KC_OAK",
                    season=2019,
                    game_type="REG",
                    week=week,
                    game_date=date(2019, 9, 1),
                    kickoff_at=kick,
                    home_team="OAK",
                    away_team="KC",
                    home_score=21,
                    away_score=17,
                    ingested_at=INGESTED_AT,
                )
            )
        session.flush()
        for week in (1, 2):
            for gsis_id, group, yards in ((RB, "RB", 50 * week), (WR, "WR", 7)):
                session.add(
                    PlayerStat(
                        gsis_id=gsis_id,
                        game_id=f"2019_0{week}_KC_OAK",
                        season=2019,
                        week=week,
                        season_type="REG",
                        position_group=group,
                        team="LV",
                        opponent_team="KC",
                        rushing_yards=yards,
                        carries=yards // 5,
                        ingested_at=INGESTED_AT,
                    )
                )
            session.add(
                DepthChart(
                    snapshot_at=KICK_1 if week == 1 else KICK_2,
                    team="LV",
                    gsis_id=RB,
                    position="RB",
                    depth_rank=1,
                    ingested_at=INGESTED_AT,
                )
            )
        session.commit()
    yield migrated_engine
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE nfl.depth_charts, nfl.player_stats, nfl.games, "
                "nfl.players, nfl.teams CASCADE"
            )
        )


def test_facts_at_or_after_kickoff_before_are_not_read(seeded: Engine) -> None:
    with seeded.connect() as conn:
        history = load_rush_history(
            conn, season_start=2019, season_end=2019, kickoff_before=KICK_2
        )

    assert {row.game_id for row in history.box_scores} == {"2019_01_KC_OAK"}
    assert {row.game_id for row in history.team_games} == {"2019_01_KC_OAK"}
    assert all(row.kickoff_at < KICK_2 for row in history.box_scores)
    assert all(row.snapshot_at < KICK_2 for row in history.depth)
    # The schedule row for the upcoming game is readable; its score is not loaded.
    assert {game.game_id for game in history.games} == {
        "2019_01_KC_OAK",
        "2019_02_KC_OAK",
    }


def test_team_game_sums_every_rusher_and_box_scores_keep_rb_history(
    seeded: Engine,
) -> None:
    with seeded.connect() as conn:
        history = load_rush_history(
            conn,
            season_start=2019,
            season_end=2019,
            kickoff_before=KICK_2 + timedelta(days=1),
        )

    allowed = {row.game_id: row.rushing_yards for row in history.team_games}
    assert allowed == {"2019_01_KC_OAK": 57, "2019_02_KC_OAK": 107}
    assert {row.gsis_id for row in history.box_scores} == {RB}
    assert history.franchise_of["OAK"] == history.franchise_of["LV"]


def test_naive_kickoff_before_raises(seeded: Engine) -> None:
    with seeded.connect() as conn, pytest.raises(ValueError, match="timezone-aware"):
        load_rush_history(
            conn,
            season_start=2019,
            season_end=2019,
            kickoff_before=datetime(2019, 9, 15),
        )
