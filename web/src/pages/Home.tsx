import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { listTeams } from "../api/teams";
import { TeamSelector } from "../components/TeamSelector";
import type { Team } from "../types/team";

export function Home() {
  const navigate = useNavigate();
  const [teams, setTeams] = useState<Team[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listTeams()
      .then((rows) => {
        if (!cancelled) {
          setTeams(rows);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load teams. Is the API running on port 8001?");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page page-home">
      <p className="eyebrow">Season explorer</p>
      <h1>Pick a team.</h1>
      <p className="lede">
        A first pass at the stats UI: one dropdown, then a team page. Logos and
        a full grid come next.
      </p>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      <TeamSelector
        teams={teams}
        value=""
        disabled={loading}
        onChange={(teamAbbr) => {
          if (teamAbbr) {
            navigate(`/teams/${teamAbbr}`);
          }
        }}
      />
    </main>
  );
}
