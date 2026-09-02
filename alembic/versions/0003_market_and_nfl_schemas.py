"""Create market and nfl schemas; move odds tables into market.

Odds capture stays in market. League entities (teams, players, injuries)
will live in nfl. SET SCHEMA on a partitioned parent does not move its
children, so each odds_observation partition is moved explicitly.

Revision ID: 0003_market_nfl_schemas
Revises: 0002_drop_2026_08
Create Date: 2026-09-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_market_nfl_schemas"
down_revision: str | None = "0002_drop_2026_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE SCHEMA market;
CREATE SCHEMA nfl;

COMMENT ON SCHEMA market IS
    'Betting-market capture: odds, snapshots, and vendor fixtures.';
COMMENT ON SCHEMA nfl IS
    'League data: teams, players, injuries, and related stats.';

ALTER TABLE public.vendor_fixture SET SCHEMA market;
ALTER TABLE public.odds_snapshot SET SCHEMA market;
ALTER TABLE public.odds_observation SET SCHEMA market;
ALTER TABLE public.odds_observation_2026_09 SET SCHEMA market;
ALTER TABLE public.odds_observation_2026_10 SET SCHEMA market;
ALTER TABLE public.odds_observation_2026_11 SET SCHEMA market;
ALTER TABLE public.odds_observation_2026_12 SET SCHEMA market;
ALTER TABLE public.odds_observation_2027_01 SET SCHEMA market;
ALTER TABLE public.odds_observation_2027_02 SET SCHEMA market;
ALTER TABLE public.odds_market_state SET SCHEMA market;
ALTER TABLE public.odds_closing_line SET SCHEMA market;
ALTER TABLE public.market_catalog SET SCHEMA market;
"""

DOWNGRADE_SQL = """
ALTER TABLE market.odds_market_state SET SCHEMA public;
ALTER TABLE market.odds_closing_line SET SCHEMA public;
ALTER TABLE market.market_catalog SET SCHEMA public;
ALTER TABLE market.odds_observation_2026_09 SET SCHEMA public;
ALTER TABLE market.odds_observation_2026_10 SET SCHEMA public;
ALTER TABLE market.odds_observation_2026_11 SET SCHEMA public;
ALTER TABLE market.odds_observation_2026_12 SET SCHEMA public;
ALTER TABLE market.odds_observation_2027_01 SET SCHEMA public;
ALTER TABLE market.odds_observation_2027_02 SET SCHEMA public;
ALTER TABLE market.odds_observation SET SCHEMA public;
ALTER TABLE market.odds_snapshot SET SCHEMA public;
ALTER TABLE market.vendor_fixture SET SCHEMA public;

DROP SCHEMA nfl;
DROP SCHEMA market;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
