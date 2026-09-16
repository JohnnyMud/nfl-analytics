import { apiGet } from "./client";
import type { Team } from "../types/team";

export function listTeams(): Promise<Team[]> {
  return apiGet<Team[]>("/teams");
}

export function getTeam(teamAbbr: string): Promise<Team> {
  return apiGet<Team>(`/teams/${encodeURIComponent(teamAbbr)}`);
}
