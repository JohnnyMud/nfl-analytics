import os
from datetime import UTC, datetime

import nflreadpy as nfl
import polars as pl

teams = (
    nfl.load_teams()
    .rename({"team_id": "franchise_id"})
    .with_columns(pl.lit(datetime.now(UTC)).alias("ingested_at"))
)

teams.write_database(
    table_name="nfl.teams",
    connection=os.environ["DATABASE_URL"],
    engine="adbc",
    if_table_exists="append",
)
