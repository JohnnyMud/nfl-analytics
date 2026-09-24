import type { Player } from "../types/player";

type PlayerSelectorProps = {
  players: Player[];
  value: string;
  disabled?: boolean;
  onChange: (gsisId: string) => void;
};

export function PlayerSelector({
  players,
  value,
  disabled = false,
  onChange,
}: PlayerSelectorProps) {
  return (
    <label className="selector">
      <span className="selector-label">Player</span>
      <select
        className="selector-control"
        value={value}
        disabled={disabled || players.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">
          {players.length === 0 ? "No players loaded yet" : "Select a player"}
        </option>
        {players.map((player) => (
          <option key={player.gsis_id} value={player.gsis_id}>
            {playerLabel(player)}
          </option>
        ))}
      </select>
    </label>
  );
}

function playerLabel(player: Player): string {
  const number = player.jersey_number ? `#${player.jersey_number} ` : "";
  const position = player.position ? ` · ${player.position}` : "";
  const status = rosterStatus(player.status);
  return `${number}${player.display_name}${position}${status ? ` · ${status}` : ""}`;
}

/** Roster designation for anyone not on the active 53. ACT is the default and unlabelled. */
function rosterStatus(status: string | null): string | null {
  switch (status) {
    case null:
      return "status unknown";
    case "ACT":
      return null;
    case "RES":
      return "IR / reserve";
    case "DEV":
      return "practice squad";
    case "EXE":
      return "exempt";
    default:
      return status;
  }
}
