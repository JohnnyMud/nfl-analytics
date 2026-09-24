import type { PlayerSeasonSummary } from "../types/player";

export type SeasonKey = { season: number; seasonType: string };

type SeasonSelectorProps = {
  seasons: PlayerSeasonSummary[];
  value: SeasonKey | null;
  onChange: (key: SeasonKey) => void;
};

export function seasonKeyToString(key: SeasonKey): string {
  return `${key.season}:${key.seasonType}`;
}

export function parseSeasonKey(raw: string): SeasonKey | null {
  const [season, seasonType] = raw.split(":");
  const year = Number(season);
  if (!Number.isInteger(year) || !seasonType) {
    return null;
  }
  return { season: year, seasonType };
}

export function SeasonSelector({ seasons, value, onChange }: SeasonSelectorProps) {
  return (
    <label className="selector selector-inline">
      <span className="selector-label">Season</span>
      <select
        className="selector-control"
        value={value ? seasonKeyToString(value) : ""}
        disabled={seasons.length === 0}
        onChange={(event) => {
          const key = parseSeasonKey(event.target.value);
          if (key) {
            onChange(key);
          }
        }}
      >
        {seasons.length === 0 ? <option value="">No seasons loaded</option> : null}
        {seasons.map((row) => {
          const key = { season: row.season, seasonType: row.season_type };
          return (
            <option key={seasonKeyToString(key)} value={seasonKeyToString(key)}>
              {seasonLabel(row)}
            </option>
          );
        })}
      </select>
    </label>
  );
}

function seasonLabel(row: PlayerSeasonSummary): string {
  const type = row.season_type === "REG" ? "" : ` ${row.season_type}`;
  const games = `${row.games} ${row.games === 1 ? "game" : "games"}`;
  return `${row.season}${type} · ${games}`;
}
