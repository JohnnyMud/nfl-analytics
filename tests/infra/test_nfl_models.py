"""ORM mappings stay aligned with the nfl schema."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from infra.models import Game, Player, PlayerStat, Team


def _column_names(conn: Connection, table: str) -> list[str]:
    return list(
        conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'nfl'
                  AND table_name = :table
                ORDER BY ordinal_position
                """
            ),
            {"table": table},
        )
        .scalars()
        .all()
    )


def test_orm_columns_match_nfl_tables(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        assert list(Team.__table__.c.keys()) == _column_names(conn, "teams")
        assert list(Player.__table__.c.keys()) == _column_names(conn, "players")
        assert list(Game.__table__.c.keys()) == _column_names(conn, "games")
        assert list(PlayerStat.__table__.c.keys()) == _column_names(
            conn, "player_stats"
        )
