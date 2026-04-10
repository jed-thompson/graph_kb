import { apiClient } from './client';
import type { PlanSessionSummary, PlanSessionDetail } from '@shared/plan-types';

export type { PlanSessionSummary, PlanSessionDetail };

export interface PlanSessionListResponse {
  sessions: PlanSessionDetail[];
  total: number;
}

export function listPlanSessions(userId?: string, params?: { limit?: number; offset?: number }): Promise<PlanSessionListResponse> {
  return apiClient.get<PlanSessionListResponse>('/plan/sessions', { ...(userId ? { user_id: userId } : {}), ...params });
}

export function getPlanSession(sessionId: string): Promise<PlanSessionDetail> {
  return apiClient.get<PlanSessionDetail>(`/plan/sessions/${sessionId}`);
}

export function renamePlanSession(sessionId: string, name: string): Promise<PlanSessionDetail> {
  return apiClient.patch<PlanSessionDetail>(`/plan/sessions/${sessionId}`, { name });
}

export function deletePlanSession(sessionId: string): Promise<{ success: boolean; session_id: string }> {
  return apiClient.delete<{ success: boolean; session_id: string }>(`/plan/sessions/${sessionId}`);
}
