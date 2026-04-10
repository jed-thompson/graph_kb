import { apiClient } from './client';
import type { GraphStats, Hotspot, EntryPoint } from '@/lib/types/api';

type RepoArg = string | { repoId: string; limit?: number };

function resolveRepo(arg: RepoArg): { id: string; limit?: number } {
  if (typeof arg === 'string') return { id: arg };
  return { id: arg.repoId, limit: arg.limit };
}

export function getGraphStats(arg: RepoArg): Promise<GraphStats> {
  const { id } = resolveRepo(arg);
  return apiClient.get<GraphStats>(`/repos/${id}/stats`);
}

export function getHotspots(arg: RepoArg): Promise<Hotspot[]> {
  const { id, limit = 20 } = resolveRepo(arg);
  return apiClient.get<Hotspot[]>(`/repos/${id}/hotspots`, { limit });
}

export function getEntryPoints(arg: RepoArg): Promise<EntryPoint[]> {
  const { id, limit = 20 } = resolveRepo(arg);
  return apiClient.get<EntryPoint[]>(`/repos/${id}/entry-points`, { limit });
}
