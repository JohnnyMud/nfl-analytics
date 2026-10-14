import { apiGet } from "./client";
import type { Player, PlayerPrediction, PlayerSeasonSummary } from "../types/player";

export function listPlayers(teamAbbr: string): Promise<Player[]> {
  const params = new URLSearchParams({ team_abbr: teamAbbr });
  return apiGet<Player[]>(`/players?${params.toString()}`);
}

export function getPlayer(gsisId: string): Promise<Player> {
  return apiGet<Player>(`/players/${encodeURIComponent(gsisId)}`);
}

export function listPlayerSeasons(gsisId: string): Promise<PlayerSeasonSummary[]> {
  return apiGet<PlayerSeasonSummary[]>(
    `/players/${encodeURIComponent(gsisId)}/seasons`,
  );
}

export function listPlayerPredictions(gsisId: string): Promise<PlayerPrediction[]> {
  return apiGet<PlayerPrediction[]>(
    `/players/${encodeURIComponent(gsisId)}/predictions`,
  );
}
