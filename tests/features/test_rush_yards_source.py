"""RushSnapshotIndex hands the builder only rows that kicked off before as_of.

In-memory ``RushHistory`` fixtures. No network, no Postgres.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from features.rush_yards import build_rush_rb_v1
from features.rush_yards_source import (
    BoxScore,
    DepthRow,
    InjuryRow,
    RushHistory,
    RushSnapshotIndex,
    RushTarget,
    ScheduledGame,
    TeamGameAllowed,
    rb_population,
    targets_from_box_scores,
)
from features.types import Known, Unknown

RB = "00-0050001"
KICK = {
    1: datetime(2019, 9, 8, 17, 0, tzinfo=UTC),
    2: datetime(2019, 9, 15, 17, 0, tzinfo=UTC),
    3: datetime(2019, 9, 22, 17, 0, tzinfo=UTC),
}
# The schedule says OAK; box scores say LV. Same franchise.
FRANCHISE = {"OAK": "2310", "LV": "2310", "KC": "2310-KC", "DEN": "2310-DEN"}


def _game(week: int, *, home: str = "OAK", away: str = "KC") -> ScheduledGame:
    return ScheduledGame(
        game_id=f"2019_{week:02d}_{away}_{home}",
        season=2019,
        week=week,
        game_type="REG",
        kickoff_at=KICK[week],
        home_team=home,
        away_team=away,
        home_rest=7,
        away_rest=7,
        div_game=True,
        roof="outdoors",
        surface="grass",
        temp=70,
        wind=5,
    )


def _box(week: int, yards: int, *, gsis_id: str = RB) -> BoxScore:
    game = _game(week)
    return BoxScore(
        gsis_id=gsis_id,
        game_id=game.game_id,
        season=2019,
        week=week,
        season_type="REG",
        position_group="RB",
        kickoff_at=KICK[week],
        team="LV",
        opponent_team="KC",
        rushing_yards=yards,
        carries=yards // 5,
    )


def _allowed(week: int, yards: int) -> TeamGameAllowed:
    # KC's defense allowed ``yards`` against LV in ``week``.
    return TeamGameAllowed(
        game_id=_game(week).game_id,
        season=2019,
        season_type="REG",
        kickoff_at=KICK[week],
        offense="LV",
        defense="KC",
        rushing_yards=yards,
        carries=yards // 4,
    )


def _history(
    box_scores: list[BoxScore],
    *,
    team_games: list[TeamGameAllowed] | None = None,
    injuries: list[InjuryRow] | None = None,
    depth: list[DepthRow] | None = None,
) -> RushHistory:
    return RushHistory(
        kickoff_before=datetime(2020, 3, 1, tzinfo=UTC),
        box_scores=tuple(box_scores),
        team_games=tuple(team_games or []),
        games=tuple(_game(week) for week in KICK),
        injuries=tuple(injuries or []),
        depth=tuple(depth or []),
        franchise_of=FRANCHISE,
    )


def _target(week: int) -> RushTarget:
    return RushTarget(
        gsis_id=RB, game_id=_game(week).game_id, team="LV", as_of=KICK[week]
    )


def test_snapshot_excludes_target_game_and_later_games() -> None:
    history = _history(
        [_box(1, 40), _box(2, 80), _box(3, 120)],
        team_games=[_allowed(1, 90), _allowed(2, 150), _allowed(3, 200)],
    )
    snapshot = RushSnapshotIndex(history).snapshot(_target(2))

    assert [row.game_id for row in snapshot.prior_player_games] == [_game(1).game_id]
    assert [row.game_id for row in snapshot.prior_opponent_games] == [_game(1).game_id]
    assert all(row.kickoff_at < KICK[2] for row in snapshot.prior_player_games)
    assert all(row.kickoff_at < KICK[2] for row in snapshot.prior_opponent_games)


def test_injected_future_rows_do_not_change_features() -> None:
    base = [_box(1, 40)]
    with_future = [*base, _box(2, 999), _box(3, 999)]
    allowed = [_allowed(1, 90)]
    allowed_future = [*allowed, _allowed(2, 999), _allowed(3, 999)]

    clean = RushSnapshotIndex(_history(base, team_games=allowed))
    leaky = RushSnapshotIndex(_history(with_future, team_games=allowed_future))

    target = _target(2)
    expected = build_rush_rb_v1(RB, target.as_of, clean.snapshot(target))
    actual = build_rush_rb_v1(RB, target.as_of, leaky.snapshot(target))
    assert actual == expected
    assert actual.player_last_rush_yards == Known[float](value=40.0)
    assert actual.opp_std_rush_yards_allowed_pg == Known[float](value=90.0)


def test_row_order_does_not_change_features() -> None:
    rows = [_box(1, 40), _box(2, 80), _box(3, 120)]
    allowed = [_allowed(1, 90), _allowed(2, 150), _allowed(3, 200)]
    ordered = RushSnapshotIndex(_history(rows, team_games=allowed))

    shuffled_rows = rows[:]
    shuffled_allowed = allowed[:]
    random.Random(7).shuffle(shuffled_rows)
    random.Random(11).shuffle(shuffled_allowed)
    shuffled = RushSnapshotIndex(_history(shuffled_rows, team_games=shuffled_allowed))

    target = _target(3)
    assert build_rush_rb_v1(RB, target.as_of, shuffled.snapshot(target)) == (
        build_rush_rb_v1(RB, target.as_of, ordered.snapshot(target))
    )


def test_relocated_club_code_still_resolves_home_and_defense() -> None:
    history = _history([_box(1, 40)], team_games=[_allowed(1, 90)])
    snapshot = RushSnapshotIndex(history).snapshot(_target(2))
    features = build_rush_rb_v1(RB, KICK[2], snapshot)

    assert features.is_home == Known[bool](value=True)
    assert features.rest_days == Known[int](value=7)
    assert features.opp_last4_rush_yards_allowed_pg == Known[float](value=90.0)


def test_injury_is_matched_on_target_week_only() -> None:
    injuries = [
        InjuryRow(
            gsis_id=RB,
            season=2019,
            week=3,
            game_type="REG",
            report_status="Questionable",
            practice_status="Limited",
        )
    ]
    index = RushSnapshotIndex(_history([_box(1, 40)], injuries=injuries))

    week2 = build_rush_rb_v1(RB, KICK[2], index.snapshot(_target(2)))
    week3 = build_rush_rb_v1(RB, KICK[3], index.snapshot(_target(3)))
    assert isinstance(week2.report_status, Unknown)
    assert week3.report_status == Known[str](value="Questionable")


def test_depth_uses_latest_snapshot_at_or_before_as_of() -> None:
    depth = [
        DepthRow(gsis_id=RB, team="LV", snapshot_at=KICK[2], depth_rank=2),
        DepthRow(
            gsis_id=RB,
            team="LV",
            snapshot_at=KICK[2] - timedelta(days=3),
            depth_rank=1,
        ),
        # Published after kickoff: must not be read.
        DepthRow(
            gsis_id=RB,
            team="LV",
            snapshot_at=KICK[2] + timedelta(minutes=1),
            depth_rank=3,
        ),
    ]
    index = RushSnapshotIndex(_history([_box(1, 40)], depth=depth))
    assert index.snapshot(_target(2)).depth_team == 2


def test_stale_or_other_club_depth_is_no_chart() -> None:
    depth = [
        DepthRow(
            gsis_id=RB,
            team="LV",
            snapshot_at=KICK[2] - timedelta(days=11),
            depth_rank=1,
        ),
        DepthRow(gsis_id=RB, team="DEN", snapshot_at=KICK[2], depth_rank=1),
    ]
    index = RushSnapshotIndex(_history([_box(1, 40)], depth=depth))
    snapshot = index.snapshot(_target(2))
    assert snapshot.depth_team is None
    features = build_rush_rb_v1(RB, KICK[2], snapshot)
    assert isinstance(features.depth_team, Unknown)


def test_unknown_game_raises() -> None:
    index = RushSnapshotIndex(_history([_box(1, 40)]))
    with pytest.raises(ValueError, match="not in the loaded schedule"):
        index.snapshot(RushTarget(gsis_id=RB, game_id="nope", team="LV", as_of=KICK[2]))


def test_population_is_reg_rb_rows_in_scored_seasons() -> None:
    qb = _box(1, 10, gsis_id="00-0050002").model_copy(update={"position_group": "QB"})
    post = _box(2, 30).model_copy(update={"season_type": "POST"})
    rows = rb_population(
        _history([_box(3, 50), qb, post, _box(1, 20)]),
        season_start=2019,
        season_end=2019,
    )
    assert [(row.week, row.gsis_id) for row in rows] == [(1, RB), (3, RB)]
    targets = targets_from_box_scores(rows)
    assert [target.as_of for target in targets] == [KICK[1], KICK[3]]
    assert all(target.team == "LV" for target in targets)
