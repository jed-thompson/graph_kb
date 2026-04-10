import { apiClient } from './client';
import type { Repository, RepoListResponse } from '@/lib/types/api';

export interface ListRepositoriesParams {
  status?: string;
  offset?: number;
  limit?: number;
}

export function listRepositories(params?: ListRepositoriesParams): Promise<RepoListResponse> {
  return apiClient.get<RepoListResponse>('/repos', params as Record<string, string | number | boolean | undefined>);
}

export function getRepository(repoId: string): Promise<Repository> {
  return apiClient.get<Repository>(`/repos/${repoId}`);
}

export function deleteRepository(repoId: string): Promise<void> {
  return apiClient.delete(`/repos/${repoId}`);
}
