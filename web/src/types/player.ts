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

/**
 * One stored rushing-yards prediction for one game and model version.
 * `y_hat` null is a model `Unknown` ("not predicted"), never 0. `y_true` is
 * the label frozen with the run; `actual_rushing_yards` is the current box
 * score, null until a box-score row exists.
 */
export type PlayerPrediction = {
  run_id: string;
  model_name: string;
  model_version: string;
  feature_set_version: string;
  game_id: string;
  season: number;
  week: number;
  kickoff_at: string | null;
  home_team: string;
  away_team: string;
  as_of: string;
  predicted_at: string;
  y_hat: number | null;
  y_true: number | null;
  actual_rushing_yards: number | null;
};
