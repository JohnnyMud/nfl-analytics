import { Link } from "react-router-dom";

import { teamLogo, withAlpha } from "./TeamCard";
import type { Player } from "../types/player";
import type { Team } from "../types/team";

type PlayerHeaderProps = {
  player: Player;
  /** Current team dimension row, or null while loading / when unknown. */
  team: Team | null;
};

export function PlayerHeader({ player, team }: PlayerHeaderProps) {
  const accent = team?.team_color ?? "var(--gold)";
  const logo = team ? teamLogo(team) : null;

  return (
    <header
      className="player-header"
      style={{
        borderTopColor: accent,
        background: team?.team_color
          ? `linear-gradient(180deg, ${withAlpha(team.team_color, 0.22)} 0%, var(--bg-elevated) 55%)`
          : undefined,
      }}
    >
      <div className="player-header-identity">
        {player.headshot ? (
          <img
            className="player-headshot"
            src={player.headshot}
            alt=""
            width={140}
            height={140}
          />
        ) : (
          <div className="player-headshot player-headshot-fallback" aria-hidden="true">
            {initials(player.display_name)}
          </div>
        )}
        <div className="player-header-title">
          <p className="eyebrow">
            {[jersey(player.jersey_number), player.position, player.latest_team]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <h1>{player.display_name}</h1>
          {team ? (
            <p className="player-header-team">
              {logo ? (
                <img src={logo} alt="" width={22} height={22} />
              ) : null}
              <Link to={`/teams/${team.team_abbr}`}>{team.team_name}</Link>
              <span className="muted"> · {team.team_division}</span>
            </p>
          ) : null}
        </div>
      </div>
      <dl className="facts player-header-facts">
        <Fact label="Age" value={age(player.birth_date)} />
        <Fact label="Ht / Wt" value={heightWeight(player.height, player.weight)} />
        <Fact label="Experience" value={experience(player)} />
        <Fact label="College" value={college(player)} />
        <Fact label="Draft" value={draftLine(player)} />
        <Fact label="Status" value={player.status} hint="as of last ingest" />
      </dl>
    </header>
  );
}

function Fact({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | null;
  hint?: string;
}) {
  return (
    <div>
      <dt>
        {label}
        {hint ? <span className="fact-hint"> ({hint})</span> : null}
      </dt>
      <dd className={value === null ? "muted" : undefined}>{value ?? "Unknown"}</dd>
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

/**
 * Whole years as of today. This is biographical display only; nothing here
 * feeds a feature, so a wall-clock read is acceptable.
 */
function age(birthDate: string | null): string | null {
  if (!birthDate) {
    return null;
  }
  const born = new Date(`${birthDate}T00:00:00Z`);
  if (Number.isNaN(born.getTime())) {
    return null;
  }
  const now = new Date();
  let years = now.getUTCFullYear() - born.getUTCFullYear();
  const beforeBirthday =
    now.getUTCMonth() < born.getUTCMonth() ||
    (now.getUTCMonth() === born.getUTCMonth() && now.getUTCDate() < born.getUTCDate());
  if (beforeBirthday) {
    years -= 1;
  }
  return `${years}`;
}

function heightWeight(height: number | null, weight: number | null): string | null {
  const feet = height === null ? null : `${Math.floor(height / 12)}'${height % 12}"`;
  const pounds = weight === null ? null : `${weight} lb`;
  if (feet === null && pounds === null) {
    return null;
  }
  return [feet, pounds].filter(Boolean).join(" · ");
}

function experience(player: Player): string | null {
  const years = player.years_of_experience;
  const span = seasonLine(player.rookie_season, player.last_season);
  if (years === null && span === null) {
    return null;
  }
  const label = years === null ? null : years === 0 ? "Rookie" : `${years} yr`;
  return [label, span].filter(Boolean).join(" · ");
}

function college(player: Player): string | null {
  if (!player.college_name) {
    return null;
  }
  return player.college_conference
    ? `${player.college_name} (${player.college_conference})`
    : player.college_name;
}

function draftLine(player: Player): string | null {
  if (player.draft_year === null && player.draft_round === null) {
    return null;
  }
  const round = player.draft_round !== null ? `Rd ${player.draft_round}` : null;
  const pick = player.draft_pick !== null ? `Pick ${player.draft_pick}` : null;
  return [player.draft_year, round, pick, player.draft_team].filter(Boolean).join(" · ");
}

function seasonLine(rookieSeason: number | null, lastSeason: number | null): string | null {
  if (rookieSeason === null && lastSeason === null) {
    return null;
  }
  return `${rookieSeason ?? "?"}–${lastSeason ?? "?"}`;
}
