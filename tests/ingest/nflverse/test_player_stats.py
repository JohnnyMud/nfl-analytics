"""Player stats transform matches nfl.player_stats weekly box scores."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ingest.nflverse.player_stats import _STAT_COLUMNS, prepare_player_stats

INGESTED_AT = datetime(2026, 9, 15, 21, 0, tzinfo=UTC)

_SOURCE_COLUMNS = tuple(
    "player_id" if column == "gsis_id" else column
    for column in _STAT_COLUMNS
    if column != "ingested_at"
)


def _source_row(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = dict.fromkeys(_SOURCE_COLUMNS)
    row.update(
        {
            "player_id": "00-0023459",
            "player_name": "A.Rodgers",
            "player_display_name": "Aaron Rodgers",
            "position": "QB",
            "position_group": "QB",
            "headshot_url": "https://example.test/headshot",
            "season": 2026,
            "week": 1,
            "season_type": "REG",
            "game_id": "2026_01_ATL_PIT",
            "team": "PIT",
            "opponent_team": "ATL",
            "completions": 22,
            "attempts": 34,
            "passing_yards": 244,
            "passing_tds": 2,
            "fantasy_points": 18.2,
        }
    )
    row.update(overrides)
    return pl.DataFrame({key: [value] for key, value in row.items()})


def test_prepare_player_stats_renames_player_id_and_stamps_ingested_at() -> None:
    out = prepare_player_stats(_source_row(), ingested_at=INGESTED_AT, season=2026)

    assert out.height == 1
    assert out["gsis_id"][0] == "00-0023459"
    assert "player_id" not in out.columns
    assert "raw" not in out.columns
    assert out["game_id"][0] == "2026_01_ATL_PIT"
    assert out["team"][0] == "PIT"
    assert out["passing_yards"][0] == 244
    assert out["ingested_at"][0] == INGESTED_AT
    assert list(out.columns) == list(_STAT_COLUMNS)


def test_prepare_player_stats_keeps_requested_season_only() -> None:
    frame = pl.concat(
        [
            _source_row(),
            _source_row(
                player_id="00-0033873",
                season=2025,
                game_id="2025_01_KC_LAC",
            ),
        ]
    )
    out = prepare_player_stats(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0023459"]
    assert out["season"].to_list() == [2026]


def test_prepare_player_stats_omits_rows_without_player_id() -> None:
    frame = pl.concat(
        [
            _source_row(),
            _source_row(
                player_id=None,
                player_display_name=None,
                game_id="2026_01_NE_SEA",
            ),
        ]
    )
    out = prepare_player_stats(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0023459"]


def test_prepare_player_stats_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_player_stats(
            _source_row(),
            ingested_at=datetime(2026, 9, 15, 21, 0),
            season=2026,
        )
