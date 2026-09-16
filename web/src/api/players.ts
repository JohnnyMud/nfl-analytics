import { apiGet } from "./client";
import type { Player } from "../types/player";

export function listPlayers(teamAbbr: string): Promise<Player[]> {
  const params = new URLSearchParams({ team_abbr: teamAbbr });
  return apiGet<Player[]>(`/players?${params.toString()}`);
}

export function getPlayer(gsisId: string): Promise<Player> {
  return apiGet<Player>(`/players/${encodeURIComponent(gsisId)}`);
}
