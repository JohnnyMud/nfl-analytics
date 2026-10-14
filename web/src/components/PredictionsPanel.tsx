import { useMemo, useState } from "react";

import { listPlayerPredictions } from "../api/players";
import { useApi } from "../hooks/useApi";
import type { PlayerPrediction } from "../types/player";

type PredictionsPanelProps = {
  gsisId: string;
};

type GameRow = {
  gameId: string;
  week: number;
  matchup: string;
  actual: number | null;
  byVersion: Map<string, number | null>;
};

/**
 * Stored rushing-yards predictions vs the box score, one row per game and one
 * column per model version. Nothing is computed beyond grouping: a missing
 * cell means that version never scored the game, and a null `y_hat` means the
 * model returned Unknown. Both render as "not predicted", never 0.
 */
export function PredictionsPanel({ gsisId }: PredictionsPanelProps) {
  const state = useApi(`${gsisId}/predictions`, () => listPlayerPredictions(gsisId));
  const predictions = state.data ?? [];
  const seasons = useMemo(
    () => [...new Set(predictions.map((row) => row.season))].sort((a, b) => b - a),
    [predictions],
  );
  const [chosen, setChosen] = useState<number | null>(null);
  const season = chosen !== null && seasons.includes(chosen) ? chosen : seasons[0] ?? null;

  const inSeason = predictions.filter((row) => row.season === season);
  const versions = [...new Set(inSeason.map((row) => row.model_version))].sort();
  const games = groupByGame(inSeason);

  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Rushing yards: predicted vs actual</h2>
        <label className="selector selector-inline">
          <span className="selector-label">Season</span>
          <select
            className="selector-control"
            value={season ?? ""}
            disabled={seasons.length === 0}
            onChange={(event) => setChosen(Number(event.target.value))}
          >
            {seasons.length === 0 ? <option value="">No predictions</option> : null}
            {seasons.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
      </div>

      {state.status === "loading" ? <p className="muted">Loading predictions…</p> : null}
      {state.status === "error" ? (
        <p className="banner banner-error" role="alert">
          Could not load predictions.
        </p>
      ) : null}
      {state.status === "ready" && predictions.length === 0 ? (
        <p className="muted">
          No stored run has scored this player. Predictions cover regular-season
          running-back games only.
        </p>
      ) : null}

      {games.length > 0 ? (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Week</th>
                  <th scope="col">Game</th>
                  <th scope="col" className="num">
                    Actual
                  </th>
                  {versions.map((version) => (
                    <th key={version} scope="col" className="num">
                      {version}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {games.map((game) => (
                  <tr key={game.gameId}>
                    <td>{game.week}</td>
                    <td>{game.matchup}</td>
                    <td className="num">
                      {game.actual === null ? (
                        <span className="muted">no box score</span>
                      ) : (
                        game.actual
                      )}
                    </td>
                    {versions.map((version) => {
                      const yHat = game.byVersion.get(version) ?? null;
                      return (
                        <td key={version} className="num">
                          {yHat === null ? (
                            <span className="muted">not predicted</span>
                          ) : (
                            yHat.toFixed(1)
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted panel-footnote">
            Read from stored walk-forward runs; each model was fit only on games
            that kicked off before this one. <code>+pregame_safe</code> uses only
            inputs known before kickoff. <code>+full</code> adds game-day weather,
            injury reports, and depth charts, so treat it as an upper bound.
          </p>
        </>
      ) : null}
    </section>
  );
}

function groupByGame(rows: PlayerPrediction[]): GameRow[] {
  const games = new Map<string, GameRow>();
  for (const row of rows) {
    let game = games.get(row.game_id);
    if (!game) {
      game = {
        gameId: row.game_id,
        week: row.week,
        matchup: `${row.away_team} @ ${row.home_team}`,
        actual: row.actual_rushing_yards,
        byVersion: new Map(),
      };
      games.set(row.game_id, game);
    }
    game.byVersion.set(row.model_version, row.y_hat);
  }
  return [...games.values()].sort((a, b) => b.week - a.week);
}
