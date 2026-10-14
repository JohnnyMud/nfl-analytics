# Spec: Rush yards phase 1

Status: Implemented — results in §11. §11 also records where the build
departed from this contract and why.
Related: `docs/architecture.md` (feature marts, LightGBM / XGBoost),
`.cursor/rules/20-modeling.mdc`, `AGENTS.md`

This file is the contract. Feature names, the `Unknown` type, the walk-forward
rule, and the two estimators are frozen here. Implementations that disagree
with this document are wrong even if tests were written first.

## 1. Purpose

Predict regular-season rushing yards for **one running back in one game**,
using only information available at that game's `kickoff_at`. After the game
is final, score the point prediction against `nfl.player_stats.rushing_yards`
with MAE and RMSE.

**Success criterion:** a stored prediction exists for every in-population
regular-season RB box-score row from 2016–2025, each carrying model version,
feature-set version, `as_of`, and run id; and a stored metric row reports MAE
and RMSE for each model, each baseline, each test season, and overall.

## 2. Non-goals

- Player-prop market baseline, CLV, or any odds feature (those lines are not
  joined to `gsis_id` yet)
- Log loss, Brier, calibration curves (this is a point prediction)
- API serving, SHAP, betting ROI
- Snap counts, Open-Meteo forecast weather, play-by-play
- scikit-learn estimators
- Scoring or retraining on 2026 until those games are final
- Inventing a box-score row for a back who does not have one

## 3. Population

A training or scoring row exists if and only if all of the following hold on
`nfl.player_stats` joined to `nfl.games`:

- `position_group = 'RB'`
- `season_type = 'REG'` (equivalently `games.game_type = 'REG'`)
- `games.kickoff_at` is not null
- the player has a box-score row for that `game_id` (zeros stay; missing rows
  are not invented)

Same-game `carries`, `rushing_yards`, and every other box-score column for
**this** `game_id` are labels. They are never features.

2012–2015 regular-season (and any preseason rows those seasons' files
contain) are loaded so 2016 week 1 has prior games. They are not scored.
2026 stays on the current-season ingest jobs and is out of this backtest.

## 4. Point-in-time type

Every feature value is `FeatureValue = Known[T] | Unknown`.

```python
# features/types.py — owned by the features worktree

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Unknown(BaseModel):
    model_config = ConfigDict(frozen=True)
    reason: str


class Known(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)
    value: T
```

Rules:

- Never return `None` for "we do not know".
- Never substitute 0, a mean, or the last observed value for a missing
  window.
- A bye or a missed game is a gap in the count of **played** games, not a
  repeated last value.
- The reason string is stored on the feature row. The training matrix maps
  `Unknown` to each booster's native missing value. No mean fill.

`as_of` is always the target game's `kickoff_at`, timezone-aware UTC. A
builder that receives a naive datetime raises `ValueError`. A builder must
be physically unable to read a prior game with `kickoff_at >= as_of`; the
in-memory snapshot is filtered on that predicate before any aggregate.

## 5. Feature set `rush_rb_v1`

Grain: one row per `(gsis_id, game_id)`. `as_of = games.kickoff_at`.
Builder signature (in-memory; no database import in `features/`):

```python
def build_rush_rb_v1(gsis_id: str, as_of: datetime, snapshot: RushSnapshot) -> RushRbV1
```

`RushSnapshot` is a pydantic model of prior player-games, prior opponent
team-games, the target game's context, the week-level injury report, and the
week-level depth-chart row. Tests construct it from fixtures. The production
assembler (training worktree) builds it from rows with `kickoff_at < as_of`
only.

Prior games for the **player** are that `gsis_id`'s box scores whose joined
`kickoff_at < as_of`, ordered by `kickoff_at`. "Played game" means a box-score
row exists. A week with no row does not invent yards or carries.

Prior games for the **opponent** are team-games in which `opponent_team` (the
defense we will face) allowed rushing yards, with `kickoff_at < as_of`.
Allowed yards for a team-game are the sum of `rushing_yards` over every
player-game row whose `opponent_team` equals that defense. Do not use this
game's box score.

### 5.1 Registry

| Name | Type | Source | As-of rule | Unknown when |
| --- | --- | --- | --- | --- |
| `player_std_rush_yards` | float | prior REG box scores, this season | kickoff &lt; as_of | no prior REG game this season |
| `player_std_carries` | float | same | same | same |
| `player_std_ypc` | float | `std_rush_yards / std_carries` | same | no prior REG game this season, or season-to-date carries = 0 |
| `player_last_rush_yards` | float | most recent prior played game (any `season_type` already kicked off) | same | no prior played game |
| `player_last_carries` | float | same | same | same |
| `player_last4_rush_yards_pg` | float | mean `rushing_yards` over the last 4 **played** games | same | no prior played game |
| `player_last4_carries_pg` | float | mean `carries` over the last 4 played games | same | same |
| `player_prior_games_this_season` | int | count of prior REG box scores this season | same | never — 0 is a known count |
| `player_prior_season_rush_yards_pg` | float | mean REG `rushing_yards` in `season - 1` | those games' kickoff &lt; as_of | no REG box score in the prior season |
| `opp_std_rush_yards_allowed_pg` | float | opponent's prior REG games this season | kickoff &lt; as_of | opponent has no prior REG game this season |
| `opp_last4_rush_yards_allowed_pg` | float | mean allowed rush yards over last 4 played opponent games | same | opponent has no prior played game |
| `is_home` | bool | `player.team == game.home_team` | target game schedule | target team is neither home nor away (must not happen; if it does, Unknown) |
| `rest_days` | int | `home_rest` or `away_rest` matching the player's team | target game schedule | matching rest column is null |
| `div_game` | bool | `games.div_game` | target game schedule | `div_game` is null |
| `roof` | str | `games.roof` | target game schedule | `roof` is null |
| `surface` | str | `games.surface` | target game schedule | `surface` is null |
| `temp` | int | `games.temp` | **game actual, not a forecast** | null, or `roof` in {`dome`, `closed`} (indoor; ignore a stale outdoor reading) |
| `wind` | int | `games.wind` | **game actual, not a forecast** | same as `temp` |
| `report_status` | str | `nfl.injuries` for `(gsis_id, season, week, game_type)` | week report treated as pre-kickoff | no injury row, or `report_status` is null |
| `practice_status` | str | same | same | no injury row, or `practice_status` is null |
| `depth_team` | int | `nfl.depth_charts` best `depth_rank` in an RB/HB slot, latest snapshot for the player's club (see §11.2) | `as_of − 10 days < snapshot_at <= as_of` | no snapshot in that window for that club |

`player_std_*` on week 1 is `Unknown`. Callers who want a week-1 usage signal
read `player_prior_season_rush_yards_pg`. Last-4 windows use however many
prior played games exist, up to 4 — they do not require a full 4 to emit a
mean. Zero prior played games is `Unknown`, not 0.

`player_prior_games_this_season` is the only count that may be 0 as a Known
value.

Injury and depth charts have no report timestamp. The week file is the
pre-kickoff state. That limitation is recorded on the feature row's source
metadata, not papered over.

`temp` and `wind` are nflverse schedule actuals. They leak a post-kickoff
weather realization. The registry says so. Do not pretend they are forecasts.
Dome / closed roof → weather is `Unknown`, never a filled 72 / 0.

`nfl.players.latest_team` and `status` are current-as-of-ingest. They are
not features and must not appear on `RushSnapshot`.

### 5.2 Leakage tests (required)

`tests/features/` constructs snapshots in memory. No network, no Postgres.

1. At game 2's `kickoff_at`, `player_last_rush_yards` equals game 1 yards and
   cannot equal game 2 or game 3 yards, even if those rows are present in the
   unfiltered fixture list.
2. A bye week between game 1 and game 3 does not copy game 1 into a
   fabricated game-2 value. `player_prior_games_this_season` is 1 entering
   game 3.
3. A missing injury row yields `Unknown(reason=...)` for both status fields,
   not `"Healthy"` and not `None`.
4. A missing depth-chart row yields `Unknown`, not `1`.
5. Indoor roof yields `Unknown` for `temp` and `wind`.
6. Naive `as_of` raises `ValueError`.

## 6. Historical data (2012–2025)

Existing loaders default to `nfl.get_current_season()`. Keep that default.
Add an explicit season range so a backfill job can load 2012–2025 without
changing the nightly current-season path.

Shared helper (backfill worktree): `ingest/nflverse/seasons.py` with
`resolve_seasons(start: int | None, end: int | None) -> tuple[int, ...]`.
`None, None` → `(current_season,)`. `start > end` raises. Each `prepare_*`
function stays **one season**; `main()` loops the resolved range.

Load order (FK):

1. Teams — already loaded; do not reload in this phase.
2. Players — every `gsis_id` referenced by those seasons' rosters, weekly
   stats, or injuries. Today's `prepare_players` keeps the current roster and
   drops `CUT` / `RET`. That stays the current-season path. Historical
   backfill must also upsert directory rows for `gsis_id`s that appear in
   stats or injuries but not on the current roster, or the fact-table FKs
   fail. Do not use `latest_team` / `status` as if they were historical.
3. Games — `prepare_schedules` per season, upsert on `game_id`.
4. Player stats — `prepare_player_stats` per season, upsert on
   `(gsis_id, game_id)`. Do not delete absent keys.
5. Injuries — `prepare_injuries` per season, upsert on
   `(gsis_id, season, week, game_type)`. `delete_absent_for_season` stays
   scoped to the season being written.
6. Depth charts — new table; see §7.

Do not delete absent player-stat or game rows. A missing row is unknown, not
a retraction.

Unit tests stay fixture-based (no network). Cover: range resolution, looping
does not leak season N into season N+1's `prepare_*` call, and historical
player upsert includes a stats-only `gsis_id`.

## 7. Depth charts

New table `nfl.depth_charts`. Migration revision `0008_nfl_depth_charts`,
`down_revision = "0007_nfl_injuries"`. This is the only first-wave
migration.

Grain: `(gsis_id, season, week, game_type, position)`.

Columns (typed nflverse copy, no `raw` jsonb):

- `season` int not null
- `week` int not null
- `game_type` text not null
- `team` text not null references `nfl.teams(team_abbr)`
- `gsis_id` text not null references `nfl.players(gsis_id)`
- `position` text not null
- `depth_position` text (nflverse formation slot, if present)
- `depth_team` int (1 = starter)
- `ingested_at` timestamptz not null

Table comment **must** state: weekly published chart, no intra-week
timestamp; `(season, week)` is treated as the pre-kickoff chart.

Source: `nflreadpy.load_depth_charts(season)`. Ingest module
`ingest/nflverse/depth_charts.py` following the injuries pattern
(`prepare_*` + `upsert_frame`, conflict on the primary key). Current-season
`main()` uses `get_current_season()`; the same season-range helper as §6
applies. SQLAlchemy `DepthChart` in `infra/models.py`.

## 8. Models

Feature-set version: `rush_rb_v1`.
Model versions: `xgb_rush_rb_v1`, `lgbm_rush_rb_v1`.

Estimators, same matrix, fixed seed `42`, no search:

| Name | Class | Parameters |
| --- | --- | --- |
| xgboost | `xgboost.XGBRegressor` | `n_estimators=400`, `max_depth=4`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, `random_state=42`, `n_jobs=1`, `tree_method="hist"`, `enable_categorical=True` |
| lightgbm | `lightgbm.LGBMRegressor` | `n_estimators=400`, `max_depth=4`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, `random_state=42`, `n_jobs=1` |

Categorical columns: `roof`, `surface`, `report_status`, `practice_status`.
Categories are the values observed in the **training window only**. A test-week
level not seen in training is missing (`Unknown` / native NA), not a new
dummy.

Early stopping, when used, takes the **previous regular season** as the eval
set. The walk-forward week is never in training or eval. If the previous
season is empty (first scored season's first weeks), skip early stopping and
fit the full `n_estimators`.

Dependencies: add `xgboost` and `lightgbm` to `pyproject.toml` in the
training worktree. Do not add scikit-learn as a required runtime dependency.

## 9. Walk-forward protocol

Time-aware only. Random k-fold is a bug.

For each regular-season week `W` in seasons 2016 through 2025, in
`(season, week)` order:

1. `cutoff` = the earliest `kickoff_at` among population games in week `W`.
2. Training rows: population games with `kickoff_at < cutoff`.
3. Eval rows for early stopping (optional): population games in
   `season - 1`.
4. Test rows: population games in week `W`.
5. Fit both boosters on the training matrix. Predict the test week.
6. After those games are final, join to `rushing_yards` and score.

Do not call `now()`. The cutoff is data-derived.

### 9.1 Baselines (mandatory)

Computed on the same `as_of` / prior-games rules as the features:

- `baseline_std`: `player_std_rush_yards` (season-to-date yards per game).
  Week 1 uses `player_prior_season_rush_yards_pg` when Known, else the
  baseline is `Unknown` and that row is excluded from that baseline's MAE /
  RMSE (count the exclusions).
- `baseline_last4`: `player_last4_rush_yards_pg`. Same Unknown handling.

A model claim requires beating both baselines on overall MAE, or the writeup
states that it did not.

### 9.2 Stored artifacts

Migration `0009_rush_rb_predictions`, `down_revision = "0008_nfl_depth_charts"`.
Schema `model` (create if missing):

`model.feature_row`

- `feature_set_version` text not null (`rush_rb_v1`)
- `gsis_id` text not null
- `game_id` text not null
- `as_of` timestamptz not null
- `payload` jsonb not null — each registry name → `{ "kind": "known", "value": ... }` or `{ "kind": "unknown", "reason": "..." }`
- `built_at` timestamptz not null
- primary key `(feature_set_version, gsis_id, game_id)`

`model.prediction`

- `run_id` uuid not null
- `model_name` text not null (`xgboost` / `lightgbm` / `baseline_std` / `baseline_last4`)
- `model_version` text not null
- `feature_set_version` text not null
- `gsis_id` text not null
- `game_id` text not null
- `as_of` timestamptz not null
- `y_hat` double precision null — null if and only if the predictor returned Unknown (baselines)
- `y_true` double precision not null — `rushing_yards` after the game is final
- `predicted_at` timestamptz not null
- primary key `(run_id, model_name, gsis_id, game_id)`

`model.metric`

- `run_id` uuid not null
- `model_name` text not null
- `season` int null — null means overall
- `mae` double precision not null
- `rmse` double precision not null
- `n` int not null
- `n_unknown` int not null — rows excluded because the predictor was Unknown
- primary key `(run_id, model_name, season)` with `NULL` season allowed via
  unique index `COALESCE(season, -1)`

A prediction without model version, feature-set version, `as_of`, and
`run_id` is not stored.

Migration `0011_prediction_y_true_nullable` relaxes `y_true` to null so
predict-upcoming can store rows before the game is played (§11.4).

## 10. Worktree split

Parent writes this spec, then merges. Implementations:

| Worktree | Owns | Must not touch |
| --- | --- | --- |
| `rush-backfill` | `ingest/nflverse/seasons.py`; season-range `main()` in players, schedules, player_stats, injuries; tests for those | Alembic, `pyproject.toml`, `features/`, `models/` |
| `rush-depth` | `alembic/versions/0008_nfl_depth_charts.py`, `ingest/nflverse/depth_charts.py`, `DepthChart` in `infra/models.py`, `tests/ingest/nflverse/test_depth_charts.py` | other ingest loaders, `pyproject.toml`, `features/` |
| `rush-features` | `features/types.py`, `features/rush_yards.py`, `tests/features/` | Alembic, ingest, `pyproject.toml` |
| `rush-train` (after features merge) | `models/rush_yards/`, `tests/models/`, `xgboost` + `lightgbm` in `pyproject.toml`, `0009_rush_rb_predictions` | ingest loaders |

Parent owns Makefile targets, schema apply, and the final `make test` /
`make lint` run.

## 11. Results

### 11.1 Departures from this contract

- **Seasons.** The warehouse starts at 2016, not 2012. 2016 is the training
  warm-up; scored seasons are **2017–2025**. 2026 is not backtested.
- **Depth charts.** §7's week-grain table was replaced before data landed by
  migration `0010_depth_chart_snapshots`: `nfl.depth_charts` is keyed
  `(gsis_id, team, snapshot_at, position)` with an integer `depth_rank`. From
  2025 `snapshot_at` is the nflverse publication time; before 2025 it is the
  club's derived kickoff, not a publication time. There is no depth-chart
  ingest job; the table was loaded once.
- **Relocated clubs.** Box scores carry current club codes (`LV`, `LAC`)
  while the schedule keeps `OAK` / `SD`. The assembler compares clubs by
  `nfl.teams.franchise_id`, so `is_home`, `rest_days`, and opponent history
  resolve for those seasons.
- **Assembler.** `features/rush_yards_source.py` is the one module in
  `features/` that reads the database (SELECT only). It bulk-loads rows with
  `kickoff_at < kickoff_before` and filters each target to `kickoff_at < as_of`
  again before `build_rush_rb_v1` runs.

### 11.2 Feature subsets

The registry stays frozen at `rush_rb_v1`. A model configuration picks a
subset, and the subset is appended to the model version:

- `pregame_safe` drops `temp`, `wind`, `report_status`, `practice_status`,
  and `depth_team`, which are not verifiably known before kickoff (weather is
  a game-day actual; injury reports have no publish time; pre-2025 depth
  snapshots are stamped at kickoff). **Headline.**
- `full` keeps all 21 features. **Upper bound only.**

`depth_team` reads the latest snapshot for the player's club with
`as_of − 10 days < snapshot_at <= as_of`, and takes the best rank across the
`RB` and `HB` slots. A stale or other-club snapshot is `Unknown`.

### 11.3 Walk-forward backtest, 2017–2025

Train from 2016, refit every regular-season week, defaults from §8 (400
trees, previous-season early stopping). Stored labels; read back with
`python -m backtest.rush_yards_report <run_id> ...`.

| run_id | subset | written |
| --- | --- | --- |
| `ea8cb8e8-8c48-4340-b5c3-243682a17ca5` | `pregame_safe` | 2026-10-14 |
| `659ca576-641a-4322-b6d4-c24f32ed9eca` | `full` | 2026-10-14 |

Each run scored 14,516 player-games in 158 weekly folds. Both runs share the
same `model.feature_row` vectors.

Overall, each model on its own rows (baselines exclude their `Unknown` rows):

| model_version | MAE | RMSE | n | unknown |
| --- | --- | --- | --- | --- |
| `lgbm_rush_rb_v1+pregame_safe` | 19.04 | 27.63 | 14,516 | 0 |
| `xgb_rush_rb_v1+pregame_safe` | 19.13 | 27.77 | 14,516 | 0 |
| `baseline_std_v1` | 19.13 | 28.66 | 14,134 | 382 |
| `baseline_last4_v1` | 19.40 | 28.83 | 14,186 | 330 |
| `lgbm_rush_rb_v1+full` | 18.82 | 27.37 | 14,516 | 0 |
| `xgb_rush_rb_v1+full` | 18.90 | 27.47 | 14,516 | 0 |

On the 14,134 player-games every model scored (the fair comparison):

| model_version | MAE | RMSE |
| --- | --- | --- |
| `lgbm_rush_rb_v1+full` | 18.95 | 27.54 |
| `xgb_rush_rb_v1+full` | 19.02 | 27.64 |
| `lgbm_rush_rb_v1+pregame_safe` | 19.11 | 27.74 |
| `baseline_std_v1` | 19.13 | 28.66 |
| `xgb_rush_rb_v1+pregame_safe` | 19.21 | 27.88 |
| `baseline_last4_v1` | 19.42 | 28.86 |

Reading:

- The pregame-safe boosters beat both baselines on RMSE by 0.8–0.9 yards on
  common rows. On MAE the margin over `baseline_std` is small: LightGBM wins
  by 0.02 and XGBoost loses by 0.08. Per §9.1, XGBoost `+pregame_safe` does
  **not** beat `baseline_std` on MAE.
- By season (each model on its own rows), the pregame-safe boosters lose to
  the better baseline on MAE in 2017–2019, win by 0.3–0.6 yards in 2020 and
  2022–2024, and are within 0.02 yards in 2021 and 2025.
- `+full` improves MAE by about 0.2 yards. That gap is the most the
  unverifiable fields could be worth, and part of it may be leakage
  (game-day weather, kickoff-stamped depth charts).

### 11.4 Upcoming games

`python -m models.rush_yards predict-upcoming --season S --week W` trains on
every population game that kicked off before the week's first kickoff and
predicts each club's RBs from its latest game this season before that cutoff.
Rows are stored with `y_true` null; the report scores them live against
`nfl.player_stats` once box scores land, and counts the rest as unlabeled,
never as zero.

| run_id | target | predictions |
| --- | --- | --- |
| `7858532a-0a46-44ab-b8a8-59db05fcc10f` | 2026 week 6, `pregame_safe` | 84 RBs × 4 models |
