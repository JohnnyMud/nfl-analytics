"""Depth-chart transform matches nfl.depth_charts weekly published charts."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ingest.nflverse.depth_charts import _DEPTH_CHART_COLUMNS, prepare_depth_charts

INGESTED_AT = datetime(2026, 9, 22, 21, 0, tzinfo=UTC)

_SOURCE_COLUMNS = tuple(c for c in _DEPTH_CHART_COLUMNS if c != "ingested_at")


def _source_row(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = dict.fromkeys(_SOURCE_COLUMNS)
    row.update(
        {
            "season": 2026,
            "week": 1,
            "game_type": "REG",
            "team": "ARI",
            "gsis_id": "00-0033893",
            "position": "RB",
            "depth_position": "RB",
            "depth_team": 1,
        }
    )
    row.update(overrides)
    return pl.DataFrame({key: [value] for key, value in row.items()})


def test_prepare_depth_charts_stamps_ingested_at() -> None:
    out = prepare_depth_charts(_source_row(), ingested_at=INGESTED_AT, season=2026)

    assert out.height == 1
    assert out["gsis_id"][0] == "00-0033893"
    assert out["team"][0] == "ARI"
    assert out["week"][0] == 1
    assert out["position"][0] == "RB"
    assert out["depth_position"][0] == "RB"
    assert out["depth_team"][0] == 1
    assert out["ingested_at"][0] == INGESTED_AT
    assert "raw" not in out.columns
    assert list(out.columns) == list(_DEPTH_CHART_COLUMNS)


def test_prepare_depth_charts_keeps_requested_season_only() -> None:
    frame = pl.concat(
        [
            _source_row(),
            _source_row(
                gsis_id="00-0030000",
                season=2025,
                week=18,
            ),
        ]
    )
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0033893"]
    assert out["season"].to_list() == [2026]


def test_prepare_depth_charts_omits_rows_without_gsis_id() -> None:
    frame = pl.concat(
        [
            _source_row(),
            _source_row(gsis_id=None, depth_position="FB"),
            _source_row(gsis_id="", depth_position="HB"),
        ]
    )
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0033893"]


def test_prepare_depth_charts_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_depth_charts(
            _source_row(),
            ingested_at=datetime(2026, 9, 22, 21, 0),
            season=2026,
        )


def test_prepare_depth_charts_maps_club_code_to_team() -> None:
    frame = _source_row().drop("team").with_columns(pl.lit("KC").alias("club_code"))
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["team"].to_list() == ["KC"]
    assert "club_code" not in out.columns
    assert list(out.columns) == list(_DEPTH_CHART_COLUMNS)


def test_prepare_depth_charts_defaults_missing_game_type_to_reg() -> None:
    frame = _source_row().drop("game_type")
    out = prepare_depth_charts(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["game_type"].to_list() == ["REG"]
