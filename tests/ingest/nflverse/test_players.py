"""Players transform keeps the current-season roster, not the career directory."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from ingest.nflverse.players import prepare_players

INGESTED_AT = datetime(2026, 9, 11, 21, 0, tzinfo=UTC)


def _roster_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "season": 2026,
        "team": "DAL",
        "position": "RB",
        "jersey_number": 25,
        "status": "ACT",
        "full_name": "Israel Abanikanda",
        "first_name": "Israel",
        "last_name": "Abanikanda",
        "birth_date": date(2002, 10, 5),
        "height": 70,
        "weight": 225,
        "college": "Pittsburgh",
        "gsis_id": "00-0038389",
        "espn_id": "4429202",
        "pff_id": "122999",
        "pfr_id": "AbanIs00",
        "years_exp": 3,
        "headshot_url": "https://example.test/roster-headshot",
        "ngs_position": "RB",
        "status_description_abbr": "A01",
        "football_name": "Israel",
        "esb_id": "ABA159567",
        "smart_id": "32004142-4115-9567-2e24-0eab29f6a4b9",
        "rookie_year": 2023,
        "draft_club": "AZ",
        "draft_number": 143,
    }
    row.update(overrides)
    return row


def _rosters(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows))


def _directory_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "gsis_id": "00-0038389",
        "display_name": "Israel Abanikanda",
        "common_first_name": "Israel",
        "first_name": "Israel",
        "last_name": "Abanikanda",
        "short_name": "I.Abanikanda",
        "football_name": "Israel",
        "suffix": None,
        "esb_id": "ABA159567",
        "nfl_id": "56008",
        "pfr_id": "AbanIs00",
        "pff_id": "122999",
        "otc_id": "10967",
        "espn_id": "4429202",
        "smart_id": "32004142-4115-9567-2e24-0eab29f6a4b9",
        "birth_date": "2002-10-05",
        "position_group": "RB",
        "position": "RB",
        "ngs_position_group": "RB",
        "ngs_position": "RB",
        "height": 70,
        "weight": 225,
        "headshot": "https://example.test/headshot",
        "college_name": "Pittsburgh",
        "college_conference": "Atlantic Coast Conference",
        "jersey_number": "25",
        "rookie_season": 2023,
        "last_season": 2026,
        "latest_team": "NYJ",
        "status": "ACT",
        "ngs_status": "ACT",
        "ngs_status_short_description": "Inactive",
        "years_of_experience": 3,
        "pff_position": "HB",
        "pff_status": "A",
        "draft_year": 2023,
        "draft_round": 5,
        "draft_pick": 143,
        "draft_team": "NYJ",
    }
    row.update(overrides)
    return row


def _directory(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows))


def test_prepare_players_keeps_roster_team_and_directory_ids() -> None:
    out = prepare_players(
        _rosters(_roster_row()),
        _directory(_directory_row()),
        ingested_at=INGESTED_AT,
    )

    assert out.height == 1
    assert out["gsis_id"][0] == "00-0038389"
    assert out["latest_team"][0] == "DAL"
    assert out["status"][0] == "ACT"
    assert out["jersey_number"][0] == "25"
    assert out["last_season"][0] == 2026
    assert out["nfl_id"][0] == "56008"
    assert out["otc_id"][0] == "10967"
    assert out["draft_round"][0] == 5
    assert out["draft_team"][0] == "NYJ"
    assert out["birth_date"][0] == date(2002, 10, 5)
    assert out["ingested_at"][0] == INGESTED_AT
    assert "raw" not in out.columns
    assert "draft_club" not in out.columns


def test_prepare_players_drops_cut_retired_and_career_only_rows() -> None:
    out = prepare_players(
        _rosters(
            _roster_row(),
            _roster_row(gsis_id="00-cut0001", full_name="Cut Player", status="CUT"),
            _roster_row(gsis_id="00-ret0001", full_name="Retired Player", status="RET"),
        ),
        _directory(
            _directory_row(),
            _directory_row(
                gsis_id="00-hist0001",
                display_name="Historical Only",
                latest_team="DAL",
            ),
        ),
        ingested_at=INGESTED_AT,
    )

    assert out["gsis_id"].to_list() == ["00-0038389"]


def test_prepare_players_keeps_practice_squad_and_roster_only_ids() -> None:
    out = prepare_players(
        _rosters(
            _roster_row(
                gsis_id="00-ps000001",
                full_name="Practice Squad",
                first_name="Practice",
                last_name="Squad",
                status="DEV",
                jersey_number=None,
            )
        ),
        _directory(_directory_row()),
        ingested_at=INGESTED_AT,
    )

    assert out.height == 1
    assert out["display_name"][0] == "Practice Squad"
    assert out["status"][0] == "DEV"
    assert out["nfl_id"][0] is None
    assert out["draft_team"][0] is None


def test_prepare_players_omits_rows_without_gsis_id() -> None:
    out = prepare_players(
        _rosters(
            _roster_row(),
            _roster_row(gsis_id=None, full_name="No Id"),
        ),
        _directory(_directory_row()),
        ingested_at=INGESTED_AT,
    )
    assert out["gsis_id"].to_list() == ["00-0038389"]


def test_prepare_players_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_players(
            _rosters(_roster_row()),
            _directory(_directory_row()),
            ingested_at=datetime(2026, 9, 11, 21, 0),
        )
