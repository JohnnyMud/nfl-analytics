"""Depth-chart transform matches nfl.depth_charts snapshot rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from ingest.nflverse.depth_charts import _DEPTH_COLUMNS, prepare_depth_charts

INGESTED_AT = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
PUBLISHED = datetime(2026, 10, 22, 12, 59, 29, tzinfo=UTC)
THURSDAY = datetime(2024, 9, 6, 0, 20, tzinfo=UTC)
SUNDAY = datetime(2024, 9, 8, 17, 0, tzinfo=UTC)
LAST_REG = datetime(2025, 1, 5, 18, 0, tzinfo=UTC)
SUPER_BOWL = datetime(2025, 2, 9, 23, 30, tzinfo=UTC)


def _timestamped_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dt": "2026-10-22T12:59:29Z",
        "team": "ARI",
        "player_name": "Josh Sweat",
        "espn_id": "3693166",
        "gsis_id": "00-0034381",
        "pos_grp_id": "4",
        "pos_grp": "Defense",
        "pos_id": "12",
        "pos_name": "Left Defensive End",
        "pos_abb": "LDE",
        "pos_slot": 1,
        "pos_rank": 1,
    }
    row.update(overrides)
    return row


def _timestamped(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows) or [_timestamped_row()])


def _weekly_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "season": 2024,
        "club_code": "SEA",
        "week": 1,
        "game_type": "REG",
        "depth_team": "1",
        "last_name": "Walker",
        "first_name": "Kenneth",
        "football_name": "Kenneth",
        "formation": "Offense",
        "gsis_id": "00-0036999",
        "jersey_number": "9",
        "position": "RB",
        "elias_id": "WAL000000",
        "depth_position": "HB",
        "full_name": "Kenneth Walker",
    }
    row.update(overrides)
    return row


def _weekly(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows) or [_weekly_row()])


def _games() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [2024, 2024, 2024, 2024, 2023],
            "week": [1, 1, 18, 22, 1],
            "game_type": ["REG", "REG", "REG", "SB", "REG"],
            "home_team": ["NO", "SEA", "SEA", "KC", "SEA"],
            "away_team": ["ATL", "ARI", "LAR", "SF", "ARI"],
            "kickoff_at": [
                THURSDAY,
                SUNDAY,
                LAST_REG,
                SUPER_BOWL,
                datetime(2023, 9, 10, 17, 0, tzinfo=UTC),
            ],
        }
    )


def _prepare_weekly(frame: pl.DataFrame, *, season: int = 2024) -> pl.DataFrame:
    return prepare_depth_charts(
        frame,
        ingested_at=INGESTED_AT,
        season=season,
        games=_games(),
    )


def test_prepare_timestamped_uses_publication_time() -> None:
    out = prepare_depth_charts(
        _timestamped(),
        ingested_at=INGESTED_AT,
        season=2026,
        games=_games(),
    )

    assert out.height == 1
    assert out["gsis_id"][0] == "00-0034381"
    assert out["team"][0] == "ARI"
    assert out["position"][0] == "LDE"
    assert out["depth_rank"][0] == 1
    assert out["snapshot_at"][0] == PUBLISHED
    assert out["snapshot_at"][0].utcoffset() is not None
    assert out["snapshot_at"][0].utcoffset().total_seconds() == 0
    assert out["ingested_at"][0] == INGESTED_AT
    assert "dt" not in out.columns
    assert "pos_name" not in out.columns
    assert list(out.columns) == list(_DEPTH_COLUMNS)


def test_prepare_timestamped_keeps_requested_season_only() -> None:
    frame = _timestamped(
        _timestamped_row(season=2026),
        _timestamped_row(gsis_id="00-0030000", season=2025, team="SEA", pos_abb="RB"),
    )
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0034381"]


def test_prepare_timestamped_omits_rows_without_gsis_id() -> None:
    frame = _timestamped(
        _timestamped_row(),
        _timestamped_row(gsis_id=None, pos_abb="WR", pos_rank=10),
    )
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0034381"]


def test_prepare_timestamped_keeps_lower_rank_for_one_slot() -> None:
    frame = _timestamped(
        _timestamped_row(pos_rank=3),
        _timestamped_row(pos_rank=1),
    )
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out.height == 1
    assert out["depth_rank"][0] == 1


def test_prepare_timestamped_keeps_distinct_slots() -> None:
    frame = _timestamped(
        _timestamped_row(pos_abb="RB", pos_rank=1),
        _timestamped_row(pos_abb="HB", pos_rank=2),
    )
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026).sort(
        "position"
    )
    assert out["position"].to_list() == ["HB", "RB"]
    assert out["depth_rank"].to_list() == [2, 1]


def test_prepare_timestamped_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_depth_charts(
            _timestamped(),
            ingested_at=datetime(2026, 10, 22, 8, 0),
            season=2026,
        )


def test_prepare_timestamped_rejects_rows_without_dt() -> None:
    frame = _timestamped(_timestamped_row(dt=None))
    with pytest.raises(ValueError, match="without dt"):
        prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)


def test_prepare_weekly_uses_club_kickoff_not_the_earlier_game() -> None:
    out = _prepare_weekly(_weekly())
    assert out.height == 1
    assert out["position"][0] == "HB"
    assert out["snapshot_at"][0] == SUNDAY
    assert out["snapshot_at"][0] != THURSDAY
    assert out["ingested_at"][0] == INGESTED_AT
    assert "club_code" not in out.columns
    assert list(out.columns) == list(_DEPTH_COLUMNS)


def test_prepare_weekly_bye_uses_earliest_kickoff_that_week() -> None:
    out = _prepare_weekly(_weekly(_weekly_row(club_code="GB", gsis_id="00-0033000")))
    assert out["snapshot_at"][0] == THURSDAY


def test_prepare_weekly_sbbye_is_super_bowl_minus_seven_days() -> None:
    out = _prepare_weekly(
        _weekly(
            _weekly_row(
                club_code="KC", gsis_id="00-0033873", week=None, game_type="SBBYE"
            )
        )
    )
    assert out["snapshot_at"][0] == SUPER_BOWL - timedelta(days=7)


def test_prepare_weekly_extra_reg_week_is_last_kickoff_plus_seven_days() -> None:
    out = _prepare_weekly(
        _weekly(
            _weekly_row(club_code="ATL", gsis_id="00-0033111", week=19, game_type="REG")
        )
    )
    assert out["snapshot_at"][0] == LAST_REG + timedelta(days=7)


def test_prepare_weekly_keeps_lower_rank_and_chart_slot() -> None:
    frame = _weekly(
        _weekly_row(depth_team="3", position="G", depth_position="RG"),
        _weekly_row(depth_team="2", position="G", depth_position="RG"),
    )
    out = _prepare_weekly(frame)
    assert out.height == 1
    assert out["position"][0] == "RG"
    assert out["depth_rank"][0] == 2


def test_prepare_weekly_omits_rows_without_gsis_id() -> None:
    frame = _weekly(_weekly_row(), _weekly_row(gsis_id=None, depth_position="WR"))
    out = _prepare_weekly(frame)
    assert out["gsis_id"].to_list() == ["00-0036999"]


def test_prepare_weekly_keeps_requested_season_only() -> None:
    frame = _weekly(
        _weekly_row(),
        _weekly_row(season=2023, gsis_id="00-0030000", club_code="SEA"),
    )
    out = _prepare_weekly(frame)
    assert out["gsis_id"].to_list() == ["00-0036999"]
    assert out["snapshot_at"][0] == SUNDAY


def test_prepare_weekly_requires_games() -> None:
    with pytest.raises(ValueError, match="need games"):
        prepare_depth_charts(_weekly(), ingested_at=INGESTED_AT, season=2024)


def test_prepare_weekly_rejects_unplaceable_week() -> None:
    frame = _weekly(_weekly_row(game_type="PRE", week=1))
    with pytest.raises(ValueError, match="PRE week 1"):
        _prepare_weekly(frame)


def test_prepare_weekly_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_depth_charts(
            _weekly(),
            ingested_at=datetime(2026, 10, 22, 8, 0),
            season=2024,
            games=_games(),
        )
