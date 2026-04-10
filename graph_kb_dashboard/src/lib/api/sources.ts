import { apiClient } from './client';

export interface SourcesResponse {
  workflow_id: string;
  sources: Record<string, unknown>[];
  total_count: number;
  repo_id: string;
  query: string;
  cached_at: number;
}

export function getSources(workflowId: string): Promise<SourcesResponse> {
  return apiClient.get<SourcesResponse>(`/sources/${workflowId}`);
}
