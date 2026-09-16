"""Schedules transform matches nfl.games after ``0005_drop_nfl_raw``."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ingest.nflverse.schedules import prepare_schedules

INGESTED_AT = datetime(2026, 9, 11, 21, 0, tzinfo=UTC)
EASTERN = ZoneInfo("America/New_York")


def _source_row(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = {
        "game_id": "2026_01_NE_SEA",
        "season": 2026,
        "game_type": "REG",
        "week": 1,
        "gameday": "2026-09-09",
        "weekday": "Wednesday",
        "gametime": "20:20",
        "away_team": "NE",
        "away_score": 10,
        "home_team": "SEA",
        "home_score": 13,
        "location": "Home",
        "result": 3,
        "total": 23,
        "overtime": 0,
        "old_game_id": "2026090900",
        "gsis": 60178,
        "nfl_detail_id": None,
        "pfr": "202609090sea",
        "pff": 30606,
        "espn": "401872656",
        "ftn": 7019,
        "away_rest": 7,
        "home_rest": 7,
        "away_moneyline": 140,
        "home_moneyline": -166,
        "spread_line": 3.0,
        "away_spread_odds": -102,
        "home_spread_odds": -118,
        "total_line": 44.5,
        "under_odds": -112,
        "over_odds": -108,
        "div_game": 0,
        "roof": "outdoors",
        "surface": "fieldturf",
        "temp": 74,
        "wind": 6,
        "away_qb_id": "00-0039851",
        "home_qb_id": "00-0034869",
        "away_qb_name": "Drake Maye",
        "home_qb_name": "Sam Darnold",
        "away_coach": "Mike Vrabel",
        "home_coach": "Mike Macdonald",
        "referee": "Adrian Hill",
        "stadium_id": "SEA00",
        "stadium": "Lumen Field",
    }
    row.update(overrides)
    return pl.DataFrame({key: [value] for key, value in row.items()})


def _kickoff_utc(game_date: date, game_time: time) -> datetime:
    return datetime.combine(game_date, game_time, tzinfo=EASTERN).astimezone(UTC)


def test_prepare_schedules_renames_clock_columns_and_stamps_ingested_at() -> None:
    out = prepare_schedules(_source_row(), ingested_at=INGESTED_AT, season=2026)

    assert out["game_id"][0] == "2026_01_NE_SEA"
    assert out["game_date"][0] == date(2026, 9, 9)
    assert out["game_time"][0] == time(20, 20)
    assert "gameday" not in out.columns
    assert "gametime" not in out.columns
    assert "raw" not in out.columns
    assert out["overtime"][0] is False
    assert out["div_game"][0] is False
    assert out["ingested_at"][0] == INGESTED_AT
    assert out["kickoff_at"][0] == _kickoff_utc(date(2026, 9, 9), time(20, 20))
    assert out["kickoff_at"][0].utcoffset() is not None
    assert out["kickoff_at"][0].utcoffset().total_seconds() == 0


def test_prepare_schedules_computes_kickoff_at_in_eastern_including_dst() -> None:
    frame = pl.concat(
        [
            _source_row(gameday="2026-09-13", gametime="13:00"),
            _source_row(
                game_id="2026_16_NE_SEA",
                gameday="2026-12-25",
                gametime="13:00",
            ),
        ]
    )
    out = prepare_schedules(frame, ingested_at=INGESTED_AT, season=2026)

    assert out["kickoff_at"][0] == datetime(2026, 9, 13, 17, 0, tzinfo=UTC)
    assert out["kickoff_at"][1] == datetime(2026, 12, 25, 18, 0, tzinfo=UTC)


def test_prepare_schedules_null_gametime_leaves_kickoff_at_unknown() -> None:
    frame = _source_row().with_columns(pl.lit(None).cast(pl.String).alias("gametime"))
    out = prepare_schedules(frame, ingested_at=INGESTED_AT, season=2026)

    assert out["game_time"][0] is None
    assert out["kickoff_at"][0] is None


def test_prepare_schedules_keeps_requested_season_only() -> None:
    frame = pl.concat(
        [
            _source_row(),
            _source_row(
                game_id="2025_01_NE_SEA",
                season=2025,
                gameday="2025-09-07",
            ),
        ]
    )
    out = prepare_schedules(frame, ingested_at=INGESTED_AT, season=2026)

    assert out["game_id"].to_list() == ["2026_01_NE_SEA"]
    assert out["season"].to_list() == [2026]


def test_prepare_schedules_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_schedules(
            _source_row(),
            ingested_at=datetime(2026, 9, 11, 21, 0),
            season=2026,
        )
