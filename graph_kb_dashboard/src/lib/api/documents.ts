import { apiClient } from './client';
import type { DocumentResponse, DocumentListResponse, DocumentFilterOptions } from '@/lib/types/api';

export interface ListDocumentsParams {
  parent?: string;
  category?: string;
  user_uploads_only?: boolean;
  offset?: number;
  limit?: number;
}

export function listDocuments(params?: ListDocumentsParams): Promise<DocumentListResponse> {
  return apiClient.get<DocumentListResponse>('/docs', params as Record<string, string | number | boolean | undefined>);
}

export function getDocument(docId: string): Promise<DocumentResponse> {
  return apiClient.get<DocumentResponse>(`/docs/${docId}`);
}

export function getFilterOptions(): Promise<DocumentFilterOptions> {
  return apiClient.get<DocumentFilterOptions>('/docs/filter-options');
}

export function uploadDocument(
  file: File,
  parent?: string,
  category?: string,
  force?: boolean,
  indexForSearch?: boolean,
): Promise<DocumentResponse> {
  const form = new FormData();
  form.append('file', file);
  if (parent) form.append('parent', parent);
  if (category) form.append('category', category);
  if (force !== undefined) form.append('force', String(force));
  if (indexForSearch !== undefined) form.append('indexed_for_search', String(indexForSearch));
  return apiClient.postForm<DocumentResponse>('/docs/upload', form);
}

export function deleteDocument(docId: string): Promise<void> {
  return apiClient.delete(`/docs/${docId}`);
}

export function updateDocumentCategory(docId: string, category: string): Promise<DocumentResponse> {
  return apiClient.patch<DocumentResponse>(`/docs/${docId}`, { category });
}
