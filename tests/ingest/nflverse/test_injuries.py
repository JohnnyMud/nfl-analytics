"""Injuries transform matches nfl.injuries weekly reports."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ingest.nflverse.injuries import _INJURY_COLUMNS, prepare_injuries

INGESTED_AT = datetime(2026, 9, 21, 21, 0, tzinfo=UTC)

_SOURCE_COLUMNS = tuple(c for c in _INJURY_COLUMNS if c != "ingested_at")


def _source_row(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = dict.fromkeys(_SOURCE_COLUMNS)
    row.update(
        {
            "season": 2026,
            "season_type": "REG",
            "game_type": "REG",
            "team": "ARI",
            "week": 1,
            "gsis_id": "00-0034381",
            "position": "LB",
            "full_name": "Josh Sweat",
            "first_name": "Josh",
            "last_name": "Sweat",
            "report_primary_injury": None,
            "report_secondary_injury": None,
            "report_status": None,
            "practice_primary_injury": "Knee",
            "practice_secondary_injury": None,
            "practice_status": "Full Participation in Practice",
        }
    )
    row.update(overrides)
    return pl.DataFrame({key: [value] for key, value in row.items()})


def test_prepare_injuries_stamps_ingested_at() -> None:
    out = prepare_injuries(_source_row(), ingested_at=INGESTED_AT, season=2026)

    assert out.height == 1
    assert out["gsis_id"][0] == "00-0034381"
    assert out["team"][0] == "ARI"
    assert out["week"][0] == 1
    assert out["report_status"][0] is None
    assert out["practice_status"][0] == "Full Participation in Practice"
    assert out["ingested_at"][0] == INGESTED_AT
    assert "raw" not in out.columns
    assert list(out.columns) == list(_INJURY_COLUMNS)


def test_prepare_injuries_keeps_requested_season_only() -> None:
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
    out = prepare_injuries(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0034381"]
    assert out["season"].to_list() == [2026]


def test_prepare_injuries_omits_rows_without_gsis_id() -> None:
    frame = pl.concat(
        [
            _source_row(),
            _source_row(gsis_id=None, full_name="Unknown"),
        ]
    )
    out = prepare_injuries(frame, ingested_at=INGESTED_AT, season=2026)
    assert out["gsis_id"].to_list() == ["00-0034381"]


def test_prepare_injuries_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_injuries(
            _source_row(),
            ingested_at=datetime(2026, 9, 21, 21, 0),
            season=2026,
        )
