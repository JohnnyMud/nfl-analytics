import type { Team } from "../types/team";

type TeamSelectorProps = {
  teams: Team[];
  value: string;
  disabled?: boolean;
  onChange: (teamAbbr: string) => void;
};

export function TeamSelector({
  teams,
  value,
  disabled = false,
  onChange,
}: TeamSelectorProps) {
  const groups = groupTeamsByDivision(teams);

  return (
    <label className="selector">
      <span className="selector-label">Team</span>
      <select
        className="selector-control"
        value={value}
        disabled={disabled || teams.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Select a team</option>
        {groups.map(([division, members]) => (
          <optgroup key={division} label={division} className="selector-group">
            {members.map((team) => (
              <option key={team.team_abbr} value={team.team_abbr}>
                {team.team_name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

function groupTeamsByDivision(teams: Team[]): [string, Team[]][] {
  const grouped = new Map<string, Team[]>();
  for (const team of teams) {
    const bucket = grouped.get(team.team_division) ?? [];
    bucket.push(team);
    grouped.set(team.team_division, bucket);
  }
  return [...grouped.entries()];
}
