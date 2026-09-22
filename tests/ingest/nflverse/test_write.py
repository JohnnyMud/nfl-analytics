"""Upsert helper: empty frames fail; re-runs update keys; injury orphans drop."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from common.settings import get_settings
from ingest.nflverse.injuries import _INJURY_COLUMNS, prepare_injuries
from ingest.nflverse.player_stats import _STAT_COLUMNS, prepare_player_stats
from ingest.nflverse.players import _PLAYER_COLUMNS, prepare_players
from ingest.nflverse.schedules import _GAME_COLUMNS, prepare_schedules
from ingest.nflverse.write import (
    _split_table,
    conflict_update_columns,
    upsert_frame,
)
from tests.infra.test_nfl_schema import _insert_game, _insert_player, _insert_team
from tests.ingest.nflverse.test_injuries import _source_row as _injury_source
from tests.ingest.nflverse.test_player_stats import _source_row as _stats_source
from tests.ingest.nflverse.test_players import (
    _directory,
    _directory_row,
    _roster_row,
    _rosters,
)
from tests.ingest.nflverse.test_schedules import _source_row as _game_source

FIRST_INGESTED = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
SECOND_INGESTED = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_conflict_update_columns_omits_keys() -> None:
    assert conflict_update_columns(
        ("gsis_id", "game_id", "passing_yards", "ingested_at"),
        ("gsis_id", "game_id"),
    ) == ("passing_yards", "ingested_at")


def test_conflict_update_columns_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="conflict columns"):
        conflict_update_columns(("gsis_id", "passing_yards"), ("game_id",))


def test_conflict_update_columns_rejects_keys_only() -> None:
    with pytest.raises(ValueError, match="every column"):
        conflict_update_columns(("gsis_id", "game_id"), ("gsis_id", "game_id"))


def test_split_table_requires_schema() -> None:
    assert _split_table("nfl.player_stats") == ("nfl", "player_stats")
    with pytest.raises(ValueError, match="schema-qualified"):
        _split_table("player_stats")


def test_upsert_frame_rejects_empty_before_connecting() -> None:
    with pytest.raises(RuntimeError, match="no player stats to ingest"):
        upsert_frame(
            pl.DataFrame({"gsis_id": [], "game_id": []}),
            table="nfl.player_stats",
            columns=("gsis_id", "game_id"),
            conflict=("gsis_id", "game_id"),
            connection_url="postgresql://invalid.example/db",
            empty_message="no player stats to ingest",
        )


def test_upsert_player_stats_updates_in_place_without_duplicate(
    migrated_engine: Engine,
) -> None:
    gsis_id = "00-0093001"
    game_id = "2026_01_UPA_UPH"
    with migrated_engine.begin() as conn:
        _insert_team(conn, "UPA", "9301", "Upsert Stats Away")
        _insert_team(conn, "UPH", "9302", "Upsert Stats Home")
        _insert_player(conn, gsis_id, "UPH")
        _insert_game(conn, game_id, "UPA", "UPH", home_qb_id=gsis_id)

    url = get_settings().postgres_url
    first = prepare_player_stats(
        _stats_source(
            player_id=gsis_id,
            game_id=game_id,
            team="UPH",
            opponent_team="UPA",
            passing_yards=244,
        ),
        ingested_at=FIRST_INGESTED,
        season=2026,
    )
    upsert_frame(
        first,
        table="nfl.player_stats",
        columns=_STAT_COLUMNS,
        conflict=("gsis_id", "game_id"),
        connection_url=url,
        empty_message="no player stats to ingest",
    )
    second = prepare_player_stats(
        _stats_source(
            player_id=gsis_id,
            game_id=game_id,
            team="UPH",
            opponent_team="UPA",
            passing_yards=301,
        ),
        ingested_at=SECOND_INGESTED,
        season=2026,
    )
    upsert_frame(
        second,
        table="nfl.player_stats",
        columns=_STAT_COLUMNS,
        conflict=("gsis_id", "game_id"),
        connection_url=url,
        empty_message="no player stats to ingest",
    )

    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT passing_yards, ingested_at
                FROM nfl.player_stats
                WHERE gsis_id = :gsis_id AND game_id = :game_id
                """
            ),
            {"gsis_id": gsis_id, "game_id": game_id},
        ).all()
    assert len(rows) == 1
    assert rows[0].passing_yards == 301
    assert rows[0].ingested_at == SECOND_INGESTED


def test_upsert_games_updates_score_in_place(migrated_engine: Engine) -> None:
    game_id = "2026_01_UGA_UGH"
    with migrated_engine.begin() as conn:
        _insert_team(conn, "UGA", "9401", "Upsert Games Away")
        _insert_team(conn, "UGH", "9402", "Upsert Games Home")

    url = get_settings().postgres_url
    first = prepare_schedules(
        _game_source(
            game_id=game_id,
            away_team="UGA",
            home_team="UGH",
            away_score=None,
            home_score=None,
            away_qb_id=None,
            home_qb_id=None,
        ),
        ingested_at=FIRST_INGESTED,
        season=2026,
    )
    upsert_frame(
        first,
        table="nfl.games",
        columns=_GAME_COLUMNS,
        conflict=("game_id",),
        connection_url=url,
        empty_message="no games to ingest",
    )
    second = prepare_schedules(
        _game_source(
            game_id=game_id,
            away_team="UGA",
            home_team="UGH",
            away_score=17,
            home_score=20,
            away_qb_id=None,
            home_qb_id=None,
        ),
        ingested_at=SECOND_INGESTED,
        season=2026,
    )
    upsert_frame(
        second,
        table="nfl.games",
        columns=_GAME_COLUMNS,
        conflict=("game_id",),
        connection_url=url,
        empty_message="no games to ingest",
    )

    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT away_score, home_score, ingested_at
                FROM nfl.games
                WHERE game_id = :game_id
                """
            ),
            {"game_id": game_id},
        ).all()
    assert len(rows) == 1
    assert rows[0].away_score == 17
    assert rows[0].home_score == 20
    assert rows[0].ingested_at == SECOND_INGESTED


def test_upsert_injuries_deletes_season_orphans(migrated_engine: Engine) -> None:
    kept = "00-0092001"
    dropped = "00-0092002"
    with migrated_engine.begin() as conn:
        _insert_team(conn, "UIT", "9201", "Upsert Injuries Team")
        _insert_player(conn, kept, "UIT")
        _insert_player(conn, dropped, "UIT")

    url = get_settings().postgres_url
    both = prepare_injuries(
        pl.concat(
            [
                _injury_source(gsis_id=kept, team="UIT", report_status="Questionable"),
                _injury_source(gsis_id=dropped, team="UIT", report_status="Out"),
            ]
        ),
        ingested_at=FIRST_INGESTED,
        season=2026,
    )
    upsert_frame(
        both,
        table="nfl.injuries",
        columns=_INJURY_COLUMNS,
        conflict=("gsis_id", "season", "week", "game_type"),
        connection_url=url,
        empty_message="no injuries to ingest",
        delete_absent_for_season=2026,
    )
    only_kept = prepare_injuries(
        _injury_source(gsis_id=kept, team="UIT", report_status="Doubtful"),
        ingested_at=SECOND_INGESTED,
        season=2026,
    )
    upsert_frame(
        only_kept,
        table="nfl.injuries",
        columns=_INJURY_COLUMNS,
        conflict=("gsis_id", "season", "week", "game_type"),
        connection_url=url,
        empty_message="no injuries to ingest",
        delete_absent_for_season=2026,
    )

    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT gsis_id, report_status, ingested_at
                FROM nfl.injuries
                WHERE team = 'UIT'
                ORDER BY gsis_id
                """
            )
        ).all()
    assert [(row.gsis_id, row.report_status) for row in rows] == [(kept, "Doubtful")]
    assert rows[0].ingested_at == SECOND_INGESTED


def test_upsert_players_updates_in_place_without_duplicate(
    migrated_engine: Engine,
) -> None:
    gsis_id = "00-0095001"
    with migrated_engine.begin() as conn:
        _insert_team(conn, "UPL", "9501", "Upsert Players Latest")
        _insert_team(conn, "UPR", "9502", "Upsert Players Roster")

    url = get_settings().postgres_url
    first = prepare_players(
        _rosters(_roster_row(gsis_id=gsis_id, team="UPL", status="ACT")),
        _directory(
            _directory_row(
                gsis_id=gsis_id,
                nfl_id="95001",
                pfr_id="UpsP9501",
                pff_id="95001",
                otc_id="95001",
                espn_id="95001",
                draft_team="UPR",
            )
        ),
        ingested_at=FIRST_INGESTED,
    )
    upsert_frame(
        first,
        table="nfl.players",
        columns=_PLAYER_COLUMNS,
        conflict=("gsis_id",),
        connection_url=url,
        empty_message="no players to ingest",
    )
    second = prepare_players(
        _rosters(_roster_row(gsis_id=gsis_id, team="UPR", status="DEV")),
        _directory(
            _directory_row(
                gsis_id=gsis_id,
                nfl_id="95001",
                pfr_id="UpsP9501",
                pff_id="95001",
                otc_id="95001",
                espn_id="95001",
                draft_team="UPR",
            )
        ),
        ingested_at=SECOND_INGESTED,
    )
    upsert_frame(
        second,
        table="nfl.players",
        columns=_PLAYER_COLUMNS,
        conflict=("gsis_id",),
        connection_url=url,
        empty_message="no players to ingest",
    )

    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT latest_team, status, ingested_at
                FROM nfl.players
                WHERE gsis_id = :gsis_id
                """
            ),
            {"gsis_id": gsis_id},
        ).all()
    assert len(rows) == 1
    assert rows[0].latest_team == "UPR"
    assert rows[0].status == "DEV"
    assert rows[0].ingested_at == SECOND_INGESTED
