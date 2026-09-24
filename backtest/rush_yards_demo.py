"""Tiny in-memory slate for the rush yards walkthrough notebook.

This is a research demo. It calls ``models.rush_yards`` so you can see fit and
predict without a warehouse backfill. The production backtest harness still
reads stored prediction rows; it does not live here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from features.rush_yards import (
    PlayerGameRow,
    RushSnapshot,
    TargetContext,
    build_rush_rb_v1,
)
from models.rush_yards import (
    LabeledRushRow,
    WalkForwardResult,
    build_matrix,
    fit_category_encoder,
    fit_lightgbm,
    fit_xgboost,
    walk_forward,
)
from models.rush_yards.estimators import FittedBooster, predict_finite

RB_A = "00-0031001"
RB_B = "00-0031002"

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
    home_away = "H" if gsis_id == RB_A else "A"
    return f"{season}_{week:02d}_{gsis_id[-4:]}_{home_away}"


def _player_game(gsis_id: str, season: int, week: int) -> PlayerGameRow:
    team = "KC" if gsis_id == RB_A else "BUF"
    opponent = "BUF" if gsis_id == RB_A else "KC"
    return PlayerGameRow(
        gsis_id=gsis_id,
        season=season,
        season_type="REG",
        kickoff_at=KICKOFFS[(season, week)],
        rushing_yards=YARDS[(gsis_id, season, week)],
        carries=15,
        team=team,
        opponent_team=opponent,
        game_id=game_id(gsis_id, season, week),
    )


def all_box_scores() -> list[PlayerGameRow]:
    return [
        _player_game(gsis_id, season, week) for (gsis_id, season, week) in sorted(YARDS)
    ]


def labeled_row(gsis_id: str, season: int, week: int) -> LabeledRushRow:
    kick = KICKOFFS[(season, week)]
    gid = game_id(gsis_id, season, week)
    team = "KC" if gsis_id == RB_A else "BUF"
    snapshot = RushSnapshot(
        prior_player_games=all_box_scores(),
        prior_opponent_games=all_box_scores(),
        target=TargetContext(
            game_id=gid,
            season=season,
            week=week,
            season_type="REG",
            kickoff_at=kick,
            player_team=team,
            home_team="KC",
            away_team="BUF",
            home_rest=7,
            away_rest=7,
            div_game=True,
            roof="outdoors",
            surface="grass",
            temp=60,
            wind=8,
        ),
        injury=None,
        depth_team=1,
    )
    return LabeledRushRow(
        gsis_id=gsis_id,
        game_id=gid,
        season=season,
        week=week,
        kickoff_at=kick,
        y_true=float(YARDS[(gsis_id, season, week)]),
        features=build_rush_rb_v1(gsis_id, kick, snapshot),
    )


def demo_population() -> list[LabeledRushRow]:
    """Two seasons, three weeks, two running backs. Features built at kickoff."""
    return [
        labeled_row(gsis_id, season, week) for (gsis_id, season, week) in sorted(YARDS)
    ]


def run_walk_forward(
    rows: list[LabeledRushRow] | None = None,
    *,
    n_estimators: int = 40,
) -> WalkForwardResult:
    """Score 2016 weeks against 2015 history. Small ``n_estimators`` for a demo."""
    slate = rows if rows is not None else demo_population()
    return walk_forward(
        slate,
        score_start=2016,
        score_end=2016,
        n_estimators=n_estimators,
    )


def fit_before_kickoff(
    rows: list[LabeledRushRow],
    as_of: datetime,
    *,
    n_estimators: int = 40,
) -> tuple[FittedBooster, FittedBooster]:
    """Fit both boosters on rows whose kickoff is strictly before ``as_of``."""
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")
    train = [row for row in rows if row.kickoff_at < as_of]
    if not train:
        raise ValueError("no training rows with kickoff_at < as_of")
    encoder = fit_category_encoder([row.features for row in train])
    matrix = build_matrix(
        [row.features for row in train],
        y=[row.y_true for row in train],
        encoder=encoder,
    )
    assert matrix.y is not None
    xgb = fit_xgboost(matrix.X, matrix.y, n_estimators=n_estimators)
    lgb = fit_lightgbm(
        matrix.X,
        matrix.y,
        n_estimators=n_estimators,
        categorical_indices=matrix.categorical_indices,
    )
    return xgb, lgb


def predict_player_game(
    rows: list[LabeledRushRow],
    gsis_id: str,
    season: int,
    week: int,
    *,
    n_estimators: int = 40,
) -> dict[str, float | str | None]:
    """Train on earlier kickoffs, then predict one held-out player-game."""
    target = next(
        row
        for row in rows
        if row.gsis_id == gsis_id and row.season == season and row.week == week
    )
    train = [row for row in rows if row.kickoff_at < target.kickoff_at]
    encoder = fit_category_encoder([row.features for row in train])
    xgb, lgb = fit_before_kickoff(rows, target.kickoff_at, n_estimators=n_estimators)
    test = build_matrix([target.features], encoder=encoder)
    return {
        "gsis_id": target.gsis_id,
        "game_id": target.game_id,
        "as_of": target.kickoff_at.isoformat(),
        "y_true": target.y_true,
        "xgboost_y_hat": predict_finite(xgb, test.X)[0],
        "lightgbm_y_hat": predict_finite(lgb, test.X)[0],
        "n_train": len(train),
    }
