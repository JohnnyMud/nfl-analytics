import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { listPlayers } from "../api/players";
import { getTeam } from "../api/teams";
import { ApiError } from "../api/client";
import { PlayerSelector } from "../components/PlayerSelector";
import { TeamCard } from "../components/TeamCard";
import type { Player } from "../types/player";
import type { Team } from "../types/team";

export function TeamPage() {
  const { teamAbbr } = useParams();
  const navigate = useNavigate();
  const [team, setTeam] = useState<Team | null>(null);
  const [players, setPlayers] = useState<Player[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!teamAbbr) {
      return;
    }
    let cancelled = false;
    setTeam(null);
    setPlayers([]);
    setError(null);

    Promise.all([getTeam(teamAbbr), listPlayers(teamAbbr)])
      .then(([nextTeam, nextPlayers]) => {
        if (!cancelled) {
          setTeam(nextTeam);
          setPlayers(nextPlayers);
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }
        if (caught instanceof ApiError && caught.status === 404) {
          setError("That team abbreviation is not in nfl.teams.");
          return;
        }
        setError("Could not load this team.");
      });

    return () => {
      cancelled = true;
    };
  }, [teamAbbr]);

  return (
    <main className="page">
      <p className="crumb">
        <Link to="/">Teams</Link>
        {teamAbbr ? <span> / {teamAbbr}</span> : null}
      </p>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {team ? <TeamCard team={team} /> : null}
      {!team && !error ? <p className="muted">Loading team…</p> : null}
      {team ? (
        <section className="panel">
          <h2>{rosterHeading(players)}</h2>
          <p className="muted">
            Current roster as of the last ingest, including reserve and
            practice-squad players, not a point-in-time depth chart. If this
            list is empty, no roster has been loaded yet.
          </p>
          <PlayerSelector
            players={players}
            value=""
            onChange={(gsisId) => {
              if (gsisId) {
                navigate(`/players/${gsisId}`);
              }
            }}
          />
        </section>
      ) : null}
    </main>
  );
}

function rosterHeading(players: Player[]): string {
  const season = players[0]?.last_season;
  return season ? `${season} roster` : "Roster";
}
