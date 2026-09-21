"""COPY + ON CONFLICT upserts for nflverse current-state tables.

Polars ``write_database`` can only append. These tables are keyed snapshots:
re-running a season file must update existing keys (stat corrections, scores)
rather than insert duplicates. Load the full prepared frame — do not watermark
on our ``ingested_at``.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import StringIO

import polars as pl
import psycopg
from psycopg import sql

_STAGING = "_nflverse_upsert"


def conflict_update_columns(
    columns: Sequence[str],
    conflict: Sequence[str],
) -> tuple[str, ...]:
    """Non-key columns written on ``ON CONFLICT DO UPDATE``."""
    known = set(columns)
    unknown = [column for column in conflict if column not in known]
    if unknown:
        raise ValueError(f"conflict columns not in frame: {unknown}")
    conflict_set = set(conflict)
    updated = tuple(column for column in columns if column not in conflict_set)
    if not updated:
        raise ValueError("conflict covers every column")
    return updated


def upsert_frame(
    frame: pl.DataFrame,
    *,
    table: str,
    columns: Sequence[str],
    conflict: Sequence[str],
    connection_url: str,
    empty_message: str,
    delete_absent_for_season: int | None = None,
) -> None:
    """COPY ``frame`` into ``table`` and upsert on ``conflict``.

    ``delete_absent_for_season`` (injuries) removes current-season keys that
    are no longer in the file. Other tables must not delete absent keys: a
    missing player-stat or game row is unknown, not a retraction.
    """
    if frame.is_empty():
        raise RuntimeError(empty_message)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"frame missing columns: {missing}")
    update_columns = conflict_update_columns(columns, conflict)
    schema, name = _split_table(table)
    if delete_absent_for_season is not None and "season" not in columns:
        raise ValueError("delete_absent_for_season requires a season column")

    dest = sql.Identifier(schema, name)
    staging = sql.Identifier(_STAGING)
    col_idents = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    conflict_idents = sql.SQL(", ").join(sql.Identifier(column) for column in conflict)
    set_clause = sql.SQL(", ").join(
        sql.SQL("{} = EXCLUDED.{}").format(
            sql.Identifier(column),
            sql.Identifier(column),
        )
        for column in update_columns
    )
    copy_sql = sql.SQL(
        "COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    ).format(staging, col_idents)
    insert_sql = sql.SQL(
        "INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) DO UPDATE SET {}"
    ).format(dest, col_idents, col_idents, staging, conflict_idents, set_clause)

    buf = StringIO()
    frame.select(*columns).write_csv(buf)

    with psycopg.connect(connection_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE TEMP TABLE {} (LIKE {})").format(staging, dest))
            with cur.copy(copy_sql) as copy:
                copy.write(buf.getvalue())
            cur.execute(insert_sql)
            if delete_absent_for_season is not None:
                cur.execute(
                    _orphan_delete_sql(dest, staging, conflict),
                    (delete_absent_for_season,),
                )
        conn.commit()


def _orphan_delete_sql(
    dest: sql.Identifier,
    staging: sql.Identifier,
    conflict: Sequence[str],
) -> sql.Composed:
    match = sql.SQL(" AND ").join(
        sql.SQL("s.{} = dest.{}").format(sql.Identifier(column), sql.Identifier(column))
        for column in conflict
    )
    return sql.SQL(
        "DELETE FROM {} AS dest WHERE dest.season = %s "
        "AND NOT EXISTS (SELECT 1 FROM {} AS s WHERE {})"
    ).format(dest, staging, match)


def _split_table(table: str) -> tuple[str, str]:
    schema, separator, name = table.partition(".")
    if not separator or not schema or not name or "." in name:
        raise ValueError(f"table must be schema-qualified, got {table!r}")
    return schema, name
