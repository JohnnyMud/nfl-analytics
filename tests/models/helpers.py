"""In-memory rush_rb_v1 rows for model tests. No network, no Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

from features.rush_yards import (
    InjuryReport,
    PlayerGameRow,
    RushSnapshot,
    TargetContext,
    build_rush_rb_v1,
)
from models.rush_yards.types import LabeledRushRow

RB_A = "00-0031001"
RB_B = "00-0031002"

# Two seasons, three REG weeks. Kickoffs are aware UTC.
KICKOFFS: dict[tuple[int, int], datetime] = {
    (2015, 1): datetime(2015, 9, 13, 17, 0, tzinfo=UTC),
    (2015, 2): datetime(2015, 9, 20, 17, 0, tzinfo=UTC),
    (2015, 3): datetime(2015, 9, 27, 17, 0, tzinfo=UTC),
    (2016, 1): datetime(2016, 9, 11, 17, 0, tzinfo=UTC),
    (2016, 2): datetime(2016, 9, 18, 17, 0, tzinfo=UTC),
    (2016, 3): datetime(2016, 9, 25, 17, 0, tzinfo=UTC),
}

# RB_A plays both seasons; RB_B is 2016-only so week-1 std baseline is Unknown.
YARDS: dict[tuple[str, int, int], int] = {
    (RB_A, 2015, 1): 50,
    (RB_A, 2015, 2): 70,
    (RB_A, 2015, 3): 90,
    (RB_A, 2016, 1): 60,
    (RB_A, 2016, 2): 80,
    (RB_A, 2016, 3): 100,
    (RB_B, 2016, 1): 40,
    (RB_B, 2016, 2): 55,
    (RB_B, 2016, 3): 65,
}


def game_id(gsis_id: str, season: int, week: int) -> str:
    return f"{season}_{week:02d}_{gsis_id[-4:]}_{'H' if gsis_id == RB_A else 'A'}"


def player_game(
    gsis_id: str,
    season: int,
    week: int,
    *,
    rushing_yards: int | None = None,
    carries: int = 15,
    team: str = "KC",
    opponent_team: str = "BUF",
    kickoff_at: datetime | None = None,
    roof_game_id: str | None = None,
) -> PlayerGameRow:
    if rushing_yards is None:
        yards = YARDS[(gsis_id, season, week)]
    else:
        yards = rushing_yards
    return PlayerGameRow(
        gsis_id=gsis_id,
        season=season,
        season_type="REG",
        kickoff_at=kickoff_at or KICKOFFS[(season, week)],
        rushing_yards=yards,
        carries=carries,
        team=team,
        opponent_team=opponent_team,
        game_id=roof_game_id or game_id(gsis_id, season, week),
    )


def all_box_scores() -> list[PlayerGameRow]:
    return [
        player_game(gsis_id, season, week) for (gsis_id, season, week) in sorted(YARDS)
    ]


def labeled_row(
    gsis_id: str,
    season: int,
    week: int,
    *,
    box_scores: list[PlayerGameRow] | None = None,
    roof: str | None = "outdoors",
    surface: str | None = "grass",
    report_status: str | None = None,
    practice_status: str | None = None,
    kickoff_at: datetime | None = None,
    y_true: float | None = None,
) -> LabeledRushRow:
    kick = kickoff_at or KICKOFFS[(season, week)]
    gid = game_id(gsis_id, season, week)
    team = "KC"
    home = "KC"
    away = "BUF"
    if gsis_id == RB_B:
        team = "BUF"
        home = "KC"
        away = "BUF"
    target = TargetContext(
        game_id=gid,
        season=season,
        week=week,
        season_type="REG",
        kickoff_at=kick,
        player_team=team,
        home_team=home,
        away_team=away,
        home_rest=7,
        away_rest=7,
        div_game=True,
        roof=roof,
        surface=surface,
        temp=60,
        wind=8,
    )
    injury = None
    if report_status is not None or practice_status is not None:
        injury = InjuryReport(
            report_status=report_status,
            practice_status=practice_status,
        )
    snapshot = RushSnapshot(
        prior_player_games=box_scores if box_scores is not None else all_box_scores(),
        prior_opponent_games=[],
        target=target,
        injury=injury,
        depth_team=1,
    )
    features = build_rush_rb_v1(gsis_id, kick, snapshot)
    yards = y_true if y_true is not None else float(YARDS[(gsis_id, season, week)])
    return LabeledRushRow(
        gsis_id=gsis_id,
        game_id=gid,
        season=season,
        week=week,
        kickoff_at=kick,
        y_true=yards,
        features=features,
    )


def population() -> list[LabeledRushRow]:
    return [
        labeled_row(gsis_id, season, week) for (gsis_id, season, week) in sorted(YARDS)
    ]
