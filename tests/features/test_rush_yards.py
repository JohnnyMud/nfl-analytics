"""Leakage and Unknown-semantics tests for rush_rb_v1. In-memory fixtures only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from features.rush_yards import (
    InjuryReport,
    PlayerGameRow,
    RushSnapshot,
    TargetContext,
    build_rush_rb_v1,
)
from features.types import Known, Unknown

GSIS_ID = "00-0033293"

GAME1_KICKOFF = datetime(2024, 9, 8, 17, 0, tzinfo=UTC)
GAME2_KICKOFF = datetime(2024, 9, 15, 17, 0, tzinfo=UTC)
GAME3_KICKOFF = datetime(2024, 9, 22, 17, 0, tzinfo=UTC)
GAME4_KICKOFF = datetime(2024, 9, 29, 17, 0, tzinfo=UTC)

GAME1_YARDS = 41
GAME2_YARDS = 99
GAME3_YARDS = 150


def _player_game(
    *,
    game_id: str,
    kickoff_at: datetime,
    rushing_yards: int,
    carries: int = 15,
    season: int = 2024,
    season_type: str = "REG",
    team: str = "KC",
    opponent_team: str = "BAL",
    gsis_id: str = GSIS_ID,
) -> PlayerGameRow:
    return PlayerGameRow(
        gsis_id=gsis_id,
        season=season,
        season_type=season_type,
        kickoff_at=kickoff_at,
        rushing_yards=rushing_yards,
        carries=carries,
        team=team,
        opponent_team=opponent_team,
        game_id=game_id,
    )


def _target(
    *,
    game_id: str,
    kickoff_at: datetime,
    week: int,
    season: int = 2024,
    season_type: str = "REG",
    player_team: str = "KC",
    home_team: str = "KC",
    away_team: str = "BUF",
    home_rest: int | None = 7,
    away_rest: int | None = 10,
    div_game: bool | None = True,
    roof: str | None = "outdoors",
    surface: str | None = "grass",
    temp: int | None = 68,
    wind: int | None = 8,
) -> TargetContext:
    return TargetContext(
        game_id=game_id,
        season=season,
        week=week,
        season_type=season_type,
        kickoff_at=kickoff_at,
        player_team=player_team,
        home_team=home_team,
        away_team=away_team,
        home_rest=home_rest,
        away_rest=away_rest,
        div_game=div_game,
        roof=roof,
        surface=surface,
        temp=temp,
        wind=wind,
    )


def _snapshot(
    *,
    target: TargetContext,
    player_games: list[PlayerGameRow] | None = None,
    opponent_games: list[PlayerGameRow] | None = None,
    injury: InjuryReport | None = None,
    depth_team: int | None = None,
) -> RushSnapshot:
    return RushSnapshot(
        prior_player_games=player_games or [],
        prior_opponent_games=opponent_games or [],
        target=target,
        injury=injury,
        depth_team=depth_team,
    )


def _assert_unknown(value: object) -> Unknown:
    assert value is not None
    assert isinstance(value, Unknown)
    assert value.reason
    return value


def _assert_known[T](value: object, expected: T) -> Known[T]:
    assert isinstance(value, Known)
    assert value.value == expected
    return value


def test_game2_kickoff_last_yards_cannot_see_game2_or_game3() -> None:
    """Game 2 kickoff last-yards equals game 1; later snapshot rows do not leak."""
    player_games = [
        _player_game(
            game_id="2024_01_BAL_KC",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=GAME1_YARDS,
        ),
        _player_game(
            game_id="2024_02_CIN_KC",
            kickoff_at=GAME2_KICKOFF,
            rushing_yards=GAME2_YARDS,
        ),
        _player_game(
            game_id="2024_03_NO_KC",
            kickoff_at=GAME3_KICKOFF,
            rushing_yards=GAME3_YARDS,
        ),
    ]
    snapshot = _snapshot(
        target=_target(game_id="2024_02_CIN_KC", kickoff_at=GAME2_KICKOFF, week=2),
        player_games=player_games,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME2_KICKOFF, snapshot)

    last = _assert_known(result.player_last_rush_yards, float(GAME1_YARDS))
    assert last.value != float(GAME2_YARDS)
    assert last.value != float(GAME3_YARDS)
    _assert_known(result.player_prior_games_this_season, 1)


def test_bye_does_not_fabricate_a_game2_value() -> None:
    """A bye is a gap in played games, not a forward-filled copy of game 1."""
    player_games = [
        _player_game(
            game_id="2024_01_BAL_KC",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=GAME1_YARDS,
            carries=12,
        ),
        _player_game(
            game_id="2024_03_NO_KC",
            kickoff_at=GAME3_KICKOFF,
            rushing_yards=GAME3_YARDS,
            carries=22,
        ),
    ]
    snapshot = _snapshot(
        target=_target(game_id="2024_03_NO_KC", kickoff_at=GAME3_KICKOFF, week=3),
        player_games=player_games,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME3_KICKOFF, snapshot)

    _assert_known(result.player_prior_games_this_season, 1)
    _assert_known(result.player_last_rush_yards, float(GAME1_YARDS))
    _assert_known(result.player_last4_rush_yards_pg, float(GAME1_YARDS))
    assert result.player_last_rush_yards.value != float(GAME3_YARDS)
    # A fabricated bye-week copy would make the window look like two games.
    # A leak of game 3 would average game 1 with game 3.
    assert result.player_last4_rush_yards_pg.value != (GAME1_YARDS + GAME3_YARDS) / 2


def test_missing_injury_is_unknown_not_healthy() -> None:
    snapshot = _snapshot(
        target=_target(game_id="2024_01_BUF_KC", kickoff_at=GAME1_KICKOFF, week=1),
        injury=None,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    report = _assert_unknown(result.report_status)
    practice = _assert_unknown(result.practice_status)
    assert report.reason != "Healthy"
    assert practice.reason != "Healthy"
    assert result.report_status is not None
    assert result.practice_status is not None
    assert getattr(result.report_status, "value", None) != "Healthy"
    assert getattr(result.practice_status, "value", None) != "Healthy"


def test_missing_depth_chart_is_unknown_not_one() -> None:
    snapshot = _snapshot(
        target=_target(game_id="2024_01_BUF_KC", kickoff_at=GAME1_KICKOFF, week=1),
        depth_team=None,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_unknown(result.depth_team)
    assert result.depth_team is not None
    assert getattr(result.depth_team, "value", None) != 1


def test_indoor_roof_makes_temp_and_wind_unknown() -> None:
    snapshot = _snapshot(
        target=_target(
            game_id="2024_01_BUF_KC",
            kickoff_at=GAME1_KICKOFF,
            week=1,
            roof="Dome",
            temp=72,
            wind=0,
        ),
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_unknown(result.temp)
    _assert_unknown(result.wind)


def test_closed_roof_is_indoor_case_insensitive() -> None:
    snapshot = _snapshot(
        target=_target(
            game_id="2024_01_BUF_KC",
            kickoff_at=GAME1_KICKOFF,
            week=1,
            roof="CLOSED",
            temp=70,
            wind=3,
        ),
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_unknown(result.temp)
    _assert_unknown(result.wind)


def test_naive_as_of_raises_value_error() -> None:
    snapshot = _snapshot(
        target=_target(game_id="2024_01_BUF_KC", kickoff_at=GAME1_KICKOFF, week=1),
    )
    naive = datetime(2024, 9, 8, 17, 0)

    with pytest.raises(ValueError):
        build_rush_rb_v1(GSIS_ID, naive, snapshot)


def test_happy_path_known_values() -> None:
    """std, last4 of 3 games, ypc, home/rest, opponent allowed excluding this game."""
    this_season = [
        _player_game(
            game_id="2024_01_BAL_KC",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=80,
            carries=20,
            opponent_team="BAL",
        ),
        _player_game(
            game_id="2024_02_CIN_KC",
            kickoff_at=GAME2_KICKOFF,
            rushing_yards=100,
            carries=25,
            opponent_team="CIN",
        ),
        _player_game(
            game_id="2024_03_NO_KC",
            kickoff_at=GAME3_KICKOFF,
            rushing_yards=60,
            carries=15,
            opponent_team="NO",
        ),
        # Same-game box score must not leak into features.
        _player_game(
            game_id="2024_04_BUF_KC",
            kickoff_at=GAME4_KICKOFF,
            rushing_yards=250,
            carries=40,
            opponent_team="BUF",
        ),
    ]

    # Allowed yards for BUF: sum rushing_yards over rows with opponent_team == BUF.
    opponent_games = [
        _player_game(
            gsis_id="00-0030001",
            game_id="2024_01_BUF_ARI",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=40,
            team="ARI",
            opponent_team="BUF",
        ),
        _player_game(
            gsis_id="00-0030002",
            game_id="2024_01_BUF_ARI",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=50,
            team="ARI",
            opponent_team="BUF",
        ),
        _player_game(
            gsis_id="00-0030003",
            game_id="2024_02_BUF_MIA",
            kickoff_at=GAME2_KICKOFF,
            rushing_yards=80,
            team="MIA",
            opponent_team="BUF",
        ),
        _player_game(
            gsis_id="00-0030004",
            game_id="2024_03_BUF_JAX",
            kickoff_at=GAME3_KICKOFF,
            rushing_yards=110,
            team="JAX",
            opponent_team="BUF",
        ),
        # Target game — huge allowed yards that must be excluded.
        _player_game(
            gsis_id="00-0030005",
            game_id="2024_04_BUF_KC",
            kickoff_at=GAME4_KICKOFF,
            rushing_yards=400,
            team="KC",
            opponent_team="BUF",
        ),
        # A different defense must not mix into BUF aggregates.
        _player_game(
            gsis_id="00-0030006",
            game_id="2024_03_BAL_CLE",
            kickoff_at=GAME3_KICKOFF,
            rushing_yards=200,
            team="CLE",
            opponent_team="BAL",
        ),
    ]

    snapshot = _snapshot(
        target=_target(
            game_id="2024_04_BUF_KC",
            kickoff_at=GAME4_KICKOFF,
            week=4,
            player_team="KC",
            home_team="KC",
            away_team="BUF",
            home_rest=7,
            away_rest=14,
            div_game=False,
            roof="outdoors",
            surface="grass",
            temp=54,
            wind=12,
        ),
        player_games=this_season,
        opponent_games=opponent_games,
        injury=InjuryReport(report_status="Questionable", practice_status="DNP"),
        depth_team=2,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME4_KICKOFF, snapshot)

    assert result.feature_set_version == "rush_rb_v1"
    assert result.gsis_id == GSIS_ID
    assert result.game_id == "2024_04_BUF_KC"
    assert result.as_of == GAME4_KICKOFF

    _assert_known(result.player_std_rush_yards, (80 + 100 + 60) / 3)
    _assert_known(result.player_std_carries, (20 + 25 + 15) / 3)
    _assert_known(result.player_std_ypc, (80 + 100 + 60) / (20 + 25 + 15))
    _assert_known(result.player_last_rush_yards, 60.0)
    _assert_known(result.player_last_carries, 15.0)
    _assert_known(result.player_last4_rush_yards_pg, (80 + 100 + 60) / 3)
    _assert_known(result.player_last4_carries_pg, (20 + 25 + 15) / 3)
    _assert_known(result.player_prior_games_this_season, 3)
    _assert_unknown(result.player_prior_season_rush_yards_pg)

    # BUF allowed 90, 80, 110 in three prior REG games. 400 on the target game is out.
    _assert_known(result.opp_std_rush_yards_allowed_pg, (90 + 80 + 110) / 3)
    _assert_known(result.opp_last4_rush_yards_allowed_pg, (90 + 80 + 110) / 3)

    _assert_known(result.is_home, True)
    _assert_known(result.rest_days, 7)
    _assert_known(result.div_game, False)
    _assert_known(result.roof, "outdoors")
    _assert_known(result.surface, "grass")
    _assert_known(result.temp, 54)
    _assert_known(result.wind, 12)
    _assert_known(result.report_status, "Questionable")
    _assert_known(result.practice_status, "DNP")
    _assert_known(result.depth_team, 2)


def test_last4_uses_three_played_games_without_requiring_four() -> None:
    this_season = [
        _player_game(
            game_id="2024_01_BAL_KC",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=80,
            carries=20,
        ),
        _player_game(
            game_id="2024_02_CIN_KC",
            kickoff_at=GAME2_KICKOFF,
            rushing_yards=100,
            carries=25,
        ),
        _player_game(
            game_id="2024_03_NO_KC",
            kickoff_at=GAME3_KICKOFF,
            rushing_yards=60,
            carries=15,
        ),
    ]
    snapshot = _snapshot(
        target=_target(game_id="2024_04_BUF_KC", kickoff_at=GAME4_KICKOFF, week=4),
        player_games=this_season,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME4_KICKOFF, snapshot)

    _assert_known(result.player_last4_rush_yards_pg, (80 + 100 + 60) / 3)
    _assert_known(result.player_last4_carries_pg, (20 + 25 + 15) / 3)
    _assert_known(result.player_prior_games_this_season, 3)


def test_week1_std_unknown_and_zero_prior_games_is_known() -> None:
    snapshot = _snapshot(
        target=_target(game_id="2024_01_BUF_KC", kickoff_at=GAME1_KICKOFF, week=1),
        player_games=[],
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_unknown(result.player_std_rush_yards)
    _assert_unknown(result.player_std_carries)
    _assert_unknown(result.player_std_ypc)
    _assert_unknown(result.player_last_rush_yards)
    _assert_unknown(result.player_last4_rush_yards_pg)
    _assert_known(result.player_prior_games_this_season, 0)
    _assert_unknown(result.player_prior_season_rush_yards_pg)


def test_ypc_unknown_when_season_to_date_carries_are_zero() -> None:
    player_games = [
        _player_game(
            game_id="2024_01_BAL_KC",
            kickoff_at=GAME1_KICKOFF,
            rushing_yards=0,
            carries=0,
        ),
    ]
    snapshot = _snapshot(
        target=_target(game_id="2024_02_CIN_KC", kickoff_at=GAME2_KICKOFF, week=2),
        player_games=player_games,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME2_KICKOFF, snapshot)

    _assert_known(result.player_std_rush_yards, 0.0)
    _assert_known(result.player_std_carries, 0.0)
    _assert_unknown(result.player_std_ypc)


def test_away_rest_and_null_schedule_fields() -> None:
    snapshot = _snapshot(
        target=_target(
            game_id="2024_01_KC_BUF",
            kickoff_at=GAME1_KICKOFF,
            week=1,
            player_team="KC",
            home_team="BUF",
            away_team="KC",
            home_rest=9,
            away_rest=6,
            div_game=None,
            roof=None,
            surface=None,
            temp=None,
            wind=None,
        ),
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_known(result.is_home, False)
    _assert_known(result.rest_days, 6)
    _assert_unknown(result.div_game)
    _assert_unknown(result.roof)
    _assert_unknown(result.surface)
    _assert_unknown(result.temp)
    _assert_unknown(result.wind)


def test_prior_season_rush_yards_pg_is_mean_of_prior_reg() -> None:
    player_games = [
        _player_game(
            game_id="2023_16_LAC_KC",
            kickoff_at=datetime(2023, 12, 31, 18, 0, tzinfo=UTC),
            rushing_yards=90,
            carries=18,
            season=2023,
            opponent_team="LAC",
        ),
        _player_game(
            game_id="2023_17_CIN_KC",
            kickoff_at=datetime(2024, 1, 7, 18, 0, tzinfo=UTC),
            rushing_yards=110,
            carries=22,
            season=2023,
            opponent_team="CIN",
        ),
        _player_game(
            game_id="2023_18_MIA_KC",
            kickoff_at=datetime(2024, 1, 13, 21, 0, tzinfo=UTC),
            rushing_yards=200,
            carries=30,
            season=2023,
            season_type="POST",
            opponent_team="MIA",
        ),
    ]
    snapshot = _snapshot(
        target=_target(game_id="2024_01_BUF_KC", kickoff_at=GAME1_KICKOFF, week=1),
        player_games=player_games,
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_known(result.player_prior_season_rush_yards_pg, (90 + 110) / 2)
    _assert_known(result.player_prior_games_this_season, 0)
    _assert_unknown(result.player_std_rush_yards)
    # Last played game is the 2023 postseason row, already kicked off.
    _assert_known(result.player_last_rush_yards, 200.0)


def test_injury_row_with_null_fields_is_unknown() -> None:
    snapshot = _snapshot(
        target=_target(game_id="2024_01_BUF_KC", kickoff_at=GAME1_KICKOFF, week=1),
        injury=InjuryReport(report_status=None, practice_status=None),
    )

    result = build_rush_rb_v1(GSIS_ID, GAME1_KICKOFF, snapshot)

    _assert_unknown(result.report_status)
    _assert_unknown(result.practice_status)
