"""Load nflverse franchise identities into nfl.teams."""

from __future__ import annotations

from datetime import UTC, datetime

import nflreadpy as nfl  # type: ignore[import-untyped]
import polars as pl

from common.settings import get_settings


def prepare_teams(frame: pl.DataFrame, *, ingested_at: datetime) -> pl.DataFrame:
    """Map an nflverse teams frame onto ``nfl.teams``.

    ``ingested_at`` is supplied by the caller; this function does not read the
    clock. nflverse dimension tables have no ``raw`` column (see migration
    ``0005_drop_nfl_raw``).
    """
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    captured = ingested_at.astimezone(UTC)
    return frame.rename({"team_id": "franchise_id"}).with_columns(
        pl.lit(captured).alias("ingested_at")
    )


def main() -> None:
    ingested_at = datetime.now(UTC)
    teams = prepare_teams(nfl.load_teams(), ingested_at=ingested_at)
    teams.write_database(
        table_name="nfl.teams",
        connection=get_settings().postgres_url,
        engine="adbc",
        if_table_exists="append",
    )


if __name__ == "__main__":
    main()
