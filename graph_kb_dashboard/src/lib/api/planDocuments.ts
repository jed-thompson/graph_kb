import { apiClient } from './client';

export const DocumentType = {
  Supporting: 'supporting',
  Reference: 'reference',
  Requirement: 'requirement',
  Primary: 'primary',
} as const;

export type DocumentType = (typeof DocumentType)[keyof typeof DocumentType] | string;

export interface PlanDocumentResponse {
  id: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  document_type: string;
  created_at?: string;
}

export interface PlanDocumentListResponse {
  documents: PlanDocumentResponse[];
  total: number;
}

export function uploadPlanDocument(sessionId: string, file: File, documentType: DocumentType = 'supporting'): Promise<PlanDocumentResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('document_type', documentType);
  return apiClient.postForm<PlanDocumentResponse>(`/plan/sessions/${sessionId}/documents`, form);
}

export function listPlanDocuments(sessionId: string): Promise<PlanDocumentListResponse> {
  return apiClient.get<PlanDocumentListResponse>(`/plan/sessions/${sessionId}/documents`);
}

export function downloadPlanDocument(sessionId: string, docId: string): Promise<string> {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000/api/v1';
  return fetch(`${API_BASE}/plan/sessions/${sessionId}/documents/${docId}`).then(r => {
    if (!r.ok) throw new Error(`Download failed: ${r.status}`);
    return r.text();
  });
}
