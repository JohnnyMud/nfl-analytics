export type Player = {
  gsis_id: string;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  short_name: string | null;
  birth_date: string | null;
  position_group: string | null;
  position: string | null;
  ngs_position: string | null;
  height: number | null;
  weight: number | null;
  headshot: string | null;
  college_name: string | null;
  college_conference: string | null;
  jersey_number: string | null;
  rookie_season: number | null;
  last_season: number | null;
  latest_team: string | null;
  status: string | null;
  years_of_experience: number | null;
  draft_year: number | null;
  draft_round: number | null;
  draft_pick: number | null;
  draft_team: string | null;
};

/**
 * Box-score totals for one (season, season_type). A null sum means every
 * stored row was null for that stat; render it as unknown, never 0.
 */
export type PlayerSeasonSummary = {
  season: number;
  season_type: string;
  games: number;
  carries: number | null;
  rushing_yards: number | null;
  rushing_tds: number | null;
  targets: number | null;
  receptions: number | null;
  receiving_yards: number | null;
  receiving_tds: number | null;
  attempts: number | null;
  completions: number | null;
  passing_yards: number | null;
  passing_tds: number | null;
  passing_interceptions: number | null;
};
