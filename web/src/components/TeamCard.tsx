import type { Team } from "../types/team";

type TeamCardProps = {
  team: Team;
};

export function TeamCard({ team }: TeamCardProps) {
  const logo = teamLogo(team);
  const accent = team.team_color ?? "#c9a227";
  const secondary = team.team_color2 ?? "#e8e6df";

  return (
    <article
      className="team-card"
      style={{
        borderTopColor: accent,
        background: `linear-gradient(180deg, ${withAlpha(accent, 0.18)} 0%, var(--surface) 42%)`,
      }}
    >
      <div className="team-card-identity">
        {logo ? (
          <img
            className="team-card-logo"
            src={logo}
            alt=""
            width={88}
            height={88}
          />
        ) : (
          <div className="team-card-logo team-card-logo-fallback" aria-hidden="true">
            {team.team_abbr}
          </div>
        )}
        <div>
          <p className="eyebrow">{team.team_abbr}</p>
          <h1 className="team-card-name">{team.team_name}</h1>
          <p className="muted">
            {team.team_conf} · {team.team_division}
          </p>
        </div>
      </div>
      <div className="team-card-swatches" aria-hidden="true">
        {[accent, secondary, team.team_color3, team.team_color4]
          .filter((color): color is string => Boolean(color))
          .map((color) => (
            <span key={color} className="swatch" style={{ background: color }} />
          ))}
      </div>
    </article>
  );
}

export function teamLogo(team: Team): string | null {
  return team.team_logo_espn ?? team.team_logo_squared ?? team.team_logo_wikipedia;
}

export function withAlpha(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  if (normalized.length !== 6) {
    return hex;
  }
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  if ([r, g, b].some((channel) => Number.isNaN(channel))) {
    return hex;
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
