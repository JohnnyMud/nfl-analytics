"""Teams transform matches nfl.teams after ``0005_drop_nfl_raw``."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ingest.nflverse.teams import prepare_teams

INGESTED_AT = datetime(2026, 9, 11, 21, 0, tzinfo=UTC)


def _source_row() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "team_abbr": ["ARI"],
            "team_name": ["Arizona Cardinals"],
            "team_id": ["3800"],
            "team_nick": ["Cardinals"],
            "team_conf": ["NFC"],
            "team_division": ["NFC West"],
            "team_color": ["#97233F"],
            "team_color2": ["#000000"],
            "team_color3": ["#ffb612"],
            "team_color4": ["#a5acaf"],
            "team_logo_wikipedia": ["https://example.test/wiki"],
            "team_logo_espn": ["https://example.test/espn"],
            "team_wordmark": ["https://example.test/wordmark"],
            "team_conference_logo": ["https://example.test/nfc"],
            "team_league_logo": ["https://example.test/nfl"],
            "team_logo_squared": ["https://example.test/sq"],
        }
    )


def test_prepare_teams_renames_team_id_and_stamps_ingested_at() -> None:
    out = prepare_teams(_source_row(), ingested_at=INGESTED_AT)

    assert out["franchise_id"][0] == "3800"
    assert "team_id" not in out.columns
    assert "raw" not in out.columns
    assert out["ingested_at"][0] == INGESTED_AT


def test_prepare_teams_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_teams(_source_row(), ingested_at=datetime(2026, 9, 11, 21, 0))
