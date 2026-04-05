import { APIRequestContext } from '@playwright/test';

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000';

/**
 * Check if the API is healthy and reachable.
 */
export async function checkApiHealth(request: APIRequestContext): Promise<boolean> {
  try {
    const response = await request.get(`${API_BASE}/health`);
    if (!response.ok()) return false;
    const data = await response.json();
    return data.status === 'ok' || data.status === 'degraded';
  } catch {
    return false;
  }
}

/**
 * Check if the database is available via the API health endpoint.
 */
export async function checkDatabaseHealth(request: APIRequestContext): Promise<boolean> {
  try {
    const response = await request.get(`${API_BASE}/api/v1/health`);
    if (!response.ok()) return false;
    const data = await response.json();
    return data.services?.database === 'available';
  } catch {
    return false;
  }
}

/**
 * Create a spec wizard session via REST API.
 */
export async function createSpecSession(
  request: APIRequestContext,
  name: string,
  description?: string,
): Promise<{ id: string; name: string; status: string }> {
  const response = await request.post(`${API_BASE}/api/v1/spec/sessions`, {
    data: { name, description },
  });
  return response.json();
}

/**
 * Get a spec wizard session via REST API.
 */
export async function getSpecSession(
  request: APIRequestContext,
  sessionId: string,
): Promise<Record<string, unknown>> {
  const response = await request.get(`${API_BASE}/api/v1/spec/sessions/${sessionId}`);
  return response.json();
}

/**
 * List spec wizard sessions via REST API.
 */
export async function listSpecSessions(
  request: APIRequestContext,
): Promise<Record<string, unknown>[]> {
  const response = await request.get(`${API_BASE}/api/v1/spec/sessions`);
  const data = await response.json();
  return data.sessions || data || [];
}

// ── Document Upload Helpers ───────────────────────────────────

/**
 * Upload a document to the general document store.
 * All documents are stored in S3, optionally indexed in ChromaDB.
 */
export async function uploadDocument(
  request: APIRequestContext,
  options: {
    filename: string;
    content: string | Buffer;
    mimeType?: string;
    parent?: string;
    indexForSearch?: boolean;
  },
): Promise<{
  id: string;
  filename: string;
  storage_key: string;
  indexed_for_search: boolean;
  file_size: number;
  mime_type: string;
  metadata: Record<string, unknown>;
}> {
  const { filename, content, mimeType = 'text/markdown', parent, indexForSearch = true } = options;

  const response = await request.post(`${API_BASE}/api/v1/docs/upload`, {
    multipart: {
      file: {
        name: filename,
        mimeType,
        buffer: typeof content === 'string' ? Buffer.from(content) : content,
      },
      ...(parent && { parent }),
      index_for_search: String(indexForSearch),
    },
  });

  return response.json();
}

/**
 * Upload a document for a spec session.
 */
export async function uploadSpecDocument(
  request: APIRequestContext,
  options: {
    sessionId: string;
    filename: string;
    content: string | Buffer;
    mimeType?: string;
    documentType?: 'primary' | 'supporting' | 'reference';
    notes?: string;
  },
): Promise<{
  id: string;
  original_filename: string;
  storage_key: string;
  sessions: Array<{ session_id: string; role: string }>;
}> {
  const { sessionId, filename, content, mimeType = 'text/markdown', documentType = 'supporting', notes } = options;

  const response = await request.post(`${API_BASE}/api/v1/spec-docs/upload`, {
    multipart: {
      file: {
        name: filename,
        mimeType,
        buffer: typeof content === 'string' ? Buffer.from(content) : content,
      },
      session_id: sessionId,
      document_type: documentType,
      ...(notes && { notes }),
    },
  });

  return response.json();
}

/**
 * Get a document by ID.
 */
export async function getDocument(
  request: APIRequestContext,
  documentId: string,
): Promise<Record<string, unknown>> {
  const response = await request.get(`${API_BASE}/api/v1/docs/${documentId}`);
  return response.json();
}

/**
 * Download a document's content.
 */
export async function downloadDocument(
  request: APIRequestContext,
  documentId: string,
): Promise<{ content: Buffer; contentType: string; filename: string }> {
  const response = await request.get(`${API_BASE}/api/v1/spec-docs/${documentId}/download`);
  return {
    content: Buffer.from(await response.body()),
    contentType: response.headers()['content-type'] || 'application/octet-stream',
    filename: response.headers()['content-disposition']?.match(/filename="(.+)"/)?.[1] || 'document',
  };
}

/**
 * List documents for a spec session.
 */
export async function listSessionDocuments(
  request: APIRequestContext,
  sessionId: string,
): Promise<{
  documents: Record<string, unknown>[];
  summary: { total_documents: number; primary_count: number; supporting_count: number; reference_count: number };
}> {
  const response = await request.get(`${API_BASE}/api/v1/spec-docs/session/${sessionId}`);
  return response.json();
}

/**
 * Delete a document (soft delete by default).
 */
export async function deleteDocument(
  request: APIRequestContext,
  documentId: string,
  permanent = false,
): Promise<boolean> {
  const response = await request.delete(`${API_BASE}/api/v1/spec-docs/${documentId}`, {
    params: { permanent: String(permanent) },
  });
  return response.status() === 204;
}
