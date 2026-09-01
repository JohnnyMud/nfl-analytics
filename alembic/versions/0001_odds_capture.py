"""Create odds capture tables.

Revision ID: 0001_odds_capture
Revises:
Create Date: 2026-09-01

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_odds_capture"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE TABLE vendor_fixture (
    vendor              text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    league              text        NOT NULL,
    season_year         int         NOT NULL,
    season_type         text        NOT NULL,
    vendor_season_week  text,
    nfl_week            int,
    start_date          timestamptz NOT NULL,
    status              text        NOT NULL,
    home_team_vendor_id text        NOT NULL,
    away_team_vendor_id text        NOT NULL,
    home_abbr           text,
    away_abbr           text,
    venue_name          text,
    venue_location      text,
    venue_neutral       bool,
    game_id             text,
    raw                 jsonb       NOT NULL,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vendor, vendor_fixture_id)
);

CREATE TABLE odds_snapshot (
    snapshot_id     bigserial   PRIMARY KEY,
    vendor          text        NOT NULL,
    tier            text        NOT NULL,
    scope           jsonb       NOT NULL,
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    outcome         text,
    requests_made   int         NOT NULL DEFAULT 0,
    quotes_seen     int         NOT NULL DEFAULT 0,
    quotes_written  int         NOT NULL DEFAULT 0,
    max_vendor_ts   timestamptz,
    error           jsonb
);

CREATE TABLE odds_observation (
    observation_id      bigserial,
    snapshot_id         bigint      NOT NULL REFERENCES odds_snapshot,
    vendor              text        NOT NULL,
    vendor_odds_id      text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    sportsbook          text        NOT NULL,
    market_id           text        NOT NULL,
    selection           text,
    selection_line      text,
    points              numeric(6,2),
    price_american      int,
    price_decimal       numeric(10,4),
    is_main             bool,
    grouping_key        text,
    vendor_player_id    text,
    vendor_team_id      text,
    limits              jsonb,
    availability        text        NOT NULL,
    vendor_timestamp    timestamptz,
    captured_at         timestamptz NOT NULL,
    raw                 jsonb       NOT NULL,
    PRIMARY KEY (observation_id, captured_at)
) PARTITION BY RANGE (captured_at);

CREATE TABLE odds_observation_2026_08 PARTITION OF odds_observation
    FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00');
CREATE TABLE odds_observation_2026_09 PARTITION OF odds_observation
    FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');
CREATE TABLE odds_observation_2026_10 PARTITION OF odds_observation
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');
CREATE TABLE odds_observation_2026_11 PARTITION OF odds_observation
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
CREATE TABLE odds_observation_2026_12 PARTITION OF odds_observation
    FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
CREATE TABLE odds_observation_2027_01 PARTITION OF odds_observation
    FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2027-02-01 00:00:00+00');
CREATE TABLE odds_observation_2027_02 PARTITION OF odds_observation
    FOR VALUES FROM ('2027-02-01 00:00:00+00') TO ('2027-03-01 00:00:00+00');

CREATE INDEX ON odds_observation (vendor_odds_id, captured_at DESC);
CREATE INDEX ON odds_observation (vendor_fixture_id, market_id, captured_at DESC);

CREATE TABLE odds_market_state (
    vendor              text        NOT NULL,
    vendor_odds_id      text        NOT NULL,
    last_observation_id bigint      NOT NULL,
    last_captured_at    timestamptz NOT NULL,
    state_hash          text        NOT NULL,
    PRIMARY KEY (vendor, vendor_odds_id),
    FOREIGN KEY (last_observation_id, last_captured_at)
        REFERENCES odds_observation (observation_id, captured_at)
);

CREATE TABLE odds_closing_line (
    vendor              text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    vendor_odds_id      text        NOT NULL,
    observation_id      bigint,
    captured_at         timestamptz,
    seconds_before_kick int,
    status              text        NOT NULL,
    PRIMARY KEY (vendor, vendor_odds_id),
    FOREIGN KEY (observation_id, captured_at)
        REFERENCES odds_observation (observation_id, captured_at)
        MATCH FULL
);

CREATE TABLE market_catalog (
    vendor              text        NOT NULL,
    vendor_fixture_id   text        NOT NULL,
    sportsbook          text        NOT NULL,
    market_id           text        NOT NULL,
    market_name         text        NOT NULL,
    first_seen_at       timestamptz NOT NULL,
    last_seen_at        timestamptz NOT NULL,
    PRIMARY KEY (vendor, vendor_fixture_id, sportsbook, market_id)
);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS odds_market_state;
DROP TABLE IF EXISTS odds_closing_line;
DROP TABLE IF EXISTS odds_observation;
DROP TABLE IF EXISTS odds_snapshot;
DROP TABLE IF EXISTS vendor_fixture;
DROP TABLE IF EXISTS market_catalog;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
