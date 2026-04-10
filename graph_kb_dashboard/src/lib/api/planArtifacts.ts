import { apiClient } from './client';

export interface PlanArtifactEntry {
  key: string;
  summary: string;
  size_bytes: number;
  created_at: string;
  content_type: string;
}

export interface PlanArtifactListResponse {
  artifacts: PlanArtifactEntry[];
  total: number;
}

export interface PlanArtifact {
  content: string;
  content_type: string;
}

export function listPlanArtifacts(sessionId: string): Promise<PlanArtifactListResponse> {
  return apiClient.get<PlanArtifactListResponse>(`/plan/sessions/${sessionId}/artifacts`);
}

export function getPlanArtifact(sessionId: string, artifactKey: string): Promise<PlanArtifact> {
  return apiClient.get<PlanArtifact>(`/plan/sessions/${sessionId}/artifacts/${artifactKey}`);
}
