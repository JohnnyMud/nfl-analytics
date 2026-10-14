import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getPlayer, listPlayerSeasons } from "../api/players";
import { getTeam } from "../api/teams";
import { PlayerHeader } from "../components/PlayerHeader";
import { PlayerTabs, type PlayerTab } from "../components/PlayerTabs";
import { PredictionsPanel } from "../components/PredictionsPanel";
import { SeasonSelector, type SeasonKey } from "../components/SeasonSelector";
import { StatCards } from "../components/StatCards";
import { isNotFound, useApi } from "../hooks/useApi";
import { buildStatCards } from "../lib/statCards";
import type { PlayerSeasonSummary } from "../types/player";

const DEFAULT_SEASON_TYPE = "REG";

export function PlayerPage() {
  const { gsisId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const playerState = useApi(gsisId || null, () => getPlayer(gsisId));
  const seasonsState = useApi(gsisId ? `${gsisId}/seasons` : null, () =>
    listPlayerSeasons(gsisId),
  );
  const player = playerState.data;
  const teamAbbr = player?.latest_team ?? null;
  const teamState = useApi(teamAbbr, () => getTeam(teamAbbr ?? ""));

  const seasons = seasonsState.data ?? [];
  const selected = useMemo(
    () => resolveSelectedSeason(seasons, searchParams.get("season"), searchParams.get("type")),
    [seasons, searchParams],
  );
  const summary = selected
    ? seasons.find(
        (row) => row.season === selected.season && row.season_type === selected.seasonType,
      ) ?? null
    : null;

  const activeTab: PlayerTab =
    searchParams.get("tab") === "predictions" ? "predictions" : "overview";

  const errorMessage = playerState.error
    ? isNotFound(playerState.error)
      ? "That player is not in nfl.players."
      : "Could not load this player."
    : null;

  return (
    <main className="page">
      <p className="crumb">
        <Link to="/">Teams</Link>
        {teamAbbr ? (
          <>
            <span> / </span>
            <Link to={`/teams/${teamAbbr}`}>{teamAbbr}</Link>
          </>
        ) : null}
        <span> / Player</span>
      </p>

      {errorMessage ? (
        <p className="banner banner-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {playerState.status === "loading" ? <p className="muted">Loading player…</p> : null}

      {player ? (
        <>
          <PlayerHeader player={player} team={teamState.data} />
          <PlayerTabs
            active={activeTab}
            onChange={(tab) => {
              const next = new URLSearchParams(searchParams);
              if (tab === "overview") {
                next.delete("tab");
              } else {
                next.set("tab", tab);
              }
              setSearchParams(next, { replace: true });
            }}
          />

          {activeTab === "predictions" ? <PredictionsPanel gsisId={gsisId} /> : null}

          {activeTab === "overview" ? (
            <section className="panel">
              <div className="panel-heading">
                <h2>Season totals</h2>
                <SeasonSelector
                  seasons={seasons}
                  value={selected}
                  onChange={(key) => {
                    const next = new URLSearchParams(searchParams);
                    next.set("season", String(key.season));
                    next.set("type", key.seasonType);
                    setSearchParams(next, { replace: true });
                  }}
                />
              </div>
              {seasonsState.status === "loading" ? (
                <p className="muted">Loading box scores…</p>
              ) : null}
              {seasonsState.status === "error" ? (
                <p className="banner banner-error" role="alert">
                  Could not load season totals.
                </p>
              ) : null}
              {seasonsState.status === "ready" && seasons.length === 0 ? (
                <p className="muted">
                  No box scores are loaded for this player. Totals appear once
                  nfl.player_stats has rows for them.
                </p>
              ) : null}
              {summary ? (
                <>
                  <StatCards cards={buildStatCards(summary, player.position)} />
                  <p className="muted panel-footnote">
                    Sums of {summary.games} final box{" "}
                    {summary.games === 1 ? "score" : "scores"} in {summary.season}
                    {summary.season_type === "REG" ? "" : ` ${summary.season_type}`}.
                    A dash means nflverse did not report that stat, not zero.
                  </p>
                </>
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

/**
 * Pick the season to show. A URL choice wins when it exists in the data;
 * otherwise the newest season, preferring REG over a same-year POST row.
 */
function resolveSelectedSeason(
  seasons: PlayerSeasonSummary[],
  rawSeason: string | null,
  rawType: string | null,
): SeasonKey | null {
  if (seasons.length === 0) {
    return null;
  }
  const wantedSeason = rawSeason === null ? null : Number(rawSeason);
  const wantedType = rawType ?? DEFAULT_SEASON_TYPE;
  if (wantedSeason !== null) {
    const match = seasons.find(
      (row) => row.season === wantedSeason && row.season_type === wantedType,
    );
    if (match) {
      return { season: match.season, seasonType: match.season_type };
    }
  }
  const newest = seasons[0].season;
  const preferred =
    seasons.find((row) => row.season === newest && row.season_type === DEFAULT_SEASON_TYPE) ??
    seasons[0];
  return { season: preferred.season, seasonType: preferred.season_type };
}
