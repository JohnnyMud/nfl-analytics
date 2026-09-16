import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { getPlayer } from "../api/players";
import type { Player } from "../types/player";

export function PlayerPage() {
  const { gsisId } = useParams();
  const [player, setPlayer] = useState<Player | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!gsisId) {
      return;
    }
    let cancelled = false;
    setPlayer(null);
    setError(null);
    getPlayer(gsisId)
      .then((row) => {
        if (!cancelled) {
          setPlayer(row);
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }
        if (caught instanceof ApiError && caught.status === 404) {
          setError("That player is not in nfl.players.");
          return;
        }
        setError("Could not load this player.");
      });
    return () => {
      cancelled = true;
    };
  }, [gsisId]);

  const teamHref = player?.latest_team
    ? `/teams/${player.latest_team}`
    : "/";

  return (
    <main className="page">
      <p className="crumb">
        <Link to="/">Teams</Link>
        {player?.latest_team ? (
          <>
            <span> / </span>
            <Link to={teamHref}>{player.latest_team}</Link>
          </>
        ) : null}
        <span> / Player</span>
      </p>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {!player && !error ? <p className="muted">Loading player…</p> : null}
      {player ? (
        <article className="player-card">
          {player.headshot ? (
            <img
              className="player-headshot"
              src={player.headshot}
              alt=""
              width={160}
              height={160}
            />
          ) : (
            <div className="player-headshot player-headshot-fallback" aria-hidden="true">
              {initials(player.display_name)}
            </div>
          )}
          <div>
            <p className="eyebrow">
              {[player.latest_team, player.position, jersey(player.jersey_number)]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <h1>{player.display_name}</h1>
            <dl className="facts">
              <Fact label="College" value={player.college_name} />
              <Fact label="Status" value={player.status} />
              <Fact
                label="Draft"
                value={draftLine(player)}
              />
              <Fact
                label="Seasons"
                value={seasonLine(player.rookie_season, player.last_season)}
              />
            </dl>
          </div>
        </article>
      ) : null}
    </main>
  );
}

function Fact({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value ?? "Unknown"}</dd>
    </div>
  );
}

function jersey(number: string | null): string | null {
  return number ? `#${number}` : null;
}

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function draftLine(player: Player): string | null {
  if (player.draft_year == null && player.draft_round == null) {
    return null;
  }
  const round = player.draft_round != null ? `Rd ${player.draft_round}` : null;
  const pick = player.draft_pick != null ? `Pick ${player.draft_pick}` : null;
  return [player.draft_year, round, pick, player.draft_team]
    .filter(Boolean)
    .join(" · ");
}

function seasonLine(
  rookieSeason: number | null,
  lastSeason: number | null,
): string | null {
  if (rookieSeason == null && lastSeason == null) {
    return null;
  }
  return `${rookieSeason ?? "?"}–${lastSeason ?? "?"}`;
}
