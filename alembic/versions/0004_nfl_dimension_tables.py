"""Create nfl.teams, nfl.players, and nfl.games.

Canonical league dimensions, shaped after nflverse load_teams / load_players /
load_schedules. team_abbr is the join key (36 rows: 32 current franchises plus
historical OAK/SD/STL/LAR). gsis_id is the player primary key. game_id is the
nflverse game id (season_week_away_home).

latest_team / status / jersey_number on players are current-as-of-ingest, not
point-in-time history. nflverse betting columns on games are historical schedule
lines, not market.odds_observation.

Revision ID: 0004_nfl_dimension_tables
Revises: 0003_market_nfl_schemas
Create Date: 2026-09-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_nfl_dimension_tables"
down_revision: str | None = "0003_market_nfl_schemas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
UPGRADE_SQL = """
CREATE TABLE nfl.teams (
    team_abbr               text        PRIMARY KEY,
    franchise_id            text        NOT NULL,
    team_name               text        NOT NULL,
    team_nick               text        NOT NULL,
    team_conf               text        NOT NULL,
    team_division           text        NOT NULL,
    team_color              text,
    team_color2             text,
    team_color3             text,
    team_color4             text,
    team_logo_wikipedia     text,
    team_logo_espn          text,
    team_wordmark           text,
    team_conference_logo    text,
    team_league_logo        text,
    team_logo_squared       text,
    ingested_at             timestamptz NOT NULL DEFAULT now(),
    raw                     jsonb       NOT NULL
);

COMMENT ON TABLE nfl.teams IS
    'NFL franchise identities keyed by abbreviation, including historical abbrs.';
COMMENT ON COLUMN nfl.teams.team_abbr IS
    'nflverse abbreviation; join key for schedules and rosters. Not unique per franchise across relocations.';
COMMENT ON COLUMN nfl.teams.franchise_id IS
    'nflverse team_id. Shared across relocation abbrs (LA/LAR/STL, LAC/SD, LV/OAK).';

CREATE INDEX ON nfl.teams (franchise_id);

CREATE TABLE nfl.players (
    gsis_id                         text        PRIMARY KEY,
    display_name                    text        NOT NULL,
    common_first_name               text,
    first_name                      text,
    last_name                       text,
    short_name                      text,
    football_name                   text,
    suffix                          text,
    esb_id                          text,
    nfl_id                          text,
    pfr_id                          text,
    pff_id                          text,
    otc_id                          text,
    espn_id                         text,
    smart_id                        text,
    birth_date                      date,
    position_group                  text,
    position                        text,
    ngs_position_group              text,
    ngs_position                    text,
    height                          int,
    weight                          int,
    headshot                        text,
    college_name                    text,
    college_conference              text,
    jersey_number                   text,
    rookie_season                   int,
    last_season                     int,
    latest_team                     text        REFERENCES nfl.teams (team_abbr),
    status                          text,
    ngs_status                      text,
    ngs_status_short_description    text,
    years_of_experience             int,
    pff_position                    text,
    pff_status                      text,
    draft_year                      int,
    draft_round                     int,
    draft_pick                      int,
    draft_team                      text        REFERENCES nfl.teams (team_abbr),
    ingested_at                     timestamptz NOT NULL DEFAULT now(),
    raw                             jsonb       NOT NULL
);

COMMENT ON TABLE nfl.players IS
    'Canonical player dimension. gsis_id is our player_id.';
COMMENT ON COLUMN nfl.players.gsis_id IS
    'NFL GSIS ID. Canonical player_id for this warehouse and nflverse joins.';
COMMENT ON COLUMN nfl.players.latest_team IS
    'Current-as-of-ingest team abbr. Not point-in-time roster history.';
COMMENT ON COLUMN nfl.players.status IS
    'Current-as-of-ingest roster status. Not point-in-time.';
COMMENT ON COLUMN nfl.players.jersey_number IS
    'Current-as-of-ingest jersey. Stored as text because nflverse ships it as a string.';

CREATE UNIQUE INDEX ON nfl.players (nfl_id) WHERE nfl_id IS NOT NULL;
CREATE UNIQUE INDEX ON nfl.players (pfr_id) WHERE pfr_id IS NOT NULL;
CREATE UNIQUE INDEX ON nfl.players (pff_id) WHERE pff_id IS NOT NULL;
CREATE UNIQUE INDEX ON nfl.players (otc_id) WHERE otc_id IS NOT NULL;
CREATE UNIQUE INDEX ON nfl.players (espn_id) WHERE espn_id IS NOT NULL;
CREATE INDEX ON nfl.players (latest_team);
CREATE INDEX ON nfl.players (last_name, first_name);

CREATE TABLE nfl.games (
    game_id             text        PRIMARY KEY,
    season              int         NOT NULL,
    game_type           text        NOT NULL,
    week                int         NOT NULL,
    game_date           date        NOT NULL,
    weekday             text,
    game_time           time,
    kickoff_at          timestamptz,
    away_team           text        NOT NULL REFERENCES nfl.teams (team_abbr),
    home_team           text        NOT NULL REFERENCES nfl.teams (team_abbr),
    away_score          int,
    home_score          int,
    location            text,
    result              int,
    total               int,
    overtime            boolean,
    old_game_id         text,
    gsis                int,
    nfl_detail_id       text,
    pfr                 text,
    pff                 int,
    espn                text,
    ftn                 int,
    away_rest           int,
    home_rest           int,
    away_moneyline      int,
    home_moneyline      int,
    spread_line         numeric(4,1),
    away_spread_odds    int,
    home_spread_odds    int,
    total_line          numeric(4,1),
    under_odds          int,
    over_odds           int,
    div_game            boolean,
    roof                text,
    surface             text,
    temp                int,
    wind                int,
    away_qb_id          text        REFERENCES nfl.players (gsis_id),
    home_qb_id          text        REFERENCES nfl.players (gsis_id),
    away_qb_name        text,
    home_qb_name        text,
    away_coach          text,
    home_coach          text,
    referee             text,
    stadium_id          text,
    stadium             text,
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    raw                 jsonb       NOT NULL,
    CHECK (home_team <> away_team)
);

COMMENT ON TABLE nfl.games IS
    'NFL games keyed by nflverse game_id (season_week_away_home).';
COMMENT ON COLUMN nfl.games.game_time IS
    'Published kickoff clock in Eastern time, not UTC.';
COMMENT ON COLUMN nfl.games.kickoff_at IS
    'UTC kickoff instant. Computed at ingest from game_date + game_time (ET).';
COMMENT ON COLUMN nfl.games.spread_line IS
    'nflverse historical home spread; not market.odds_observation.';
COMMENT ON COLUMN nfl.games.away_score IS
    'Null until the game is played. Null is unknown, not a 0-0 game.';

CREATE INDEX ON nfl.games (season, week);
CREATE INDEX ON nfl.games (kickoff_at);
CREATE INDEX ON nfl.games (home_team, season);
CREATE INDEX ON nfl.games (away_team, season);
"""

DOWNGRADE_SQL = """
DROP TABLE nfl.games;
DROP TABLE nfl.players;
DROP TABLE nfl.teams;
"""
# fmt: on


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
