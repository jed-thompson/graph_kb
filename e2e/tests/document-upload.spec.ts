import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000';

/**
 * E2E tests for Document Upload with S3 Blob Storage and optional ChromaDB indexing.
 *
 * Tests:
 * 1. Upload document with ChromaDB indexing (default)
 * 2. Upload document without ChromaDB indexing (S3 only)
 * 3. Upload binary file (PDF/image) - S3 only
 * 4. Verify document is stored in S3 via download
 * 5. List and retrieve documents
 * 6. Spec document upload for spec sessions
 */

test.describe('Document Upload - S3 Storage', () => {
  test.beforeEach(async ({ request }) => {
    // Check API health
    const healthResponse = await request.get(`${API_BASE}/health`);
    expect(healthResponse.ok()).toBeTruthy();
  });

  test('POST /docs/upload - text file with ChromaDB indexing (default)', async ({ request }) => {
    // Create a text file content
    const fileContent = `# Test Document\n\nThis is a test document for e2e testing.\nCreated at: ${new Date().toISOString()}`;

    // Upload with multipart form
    const response = await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 'test-doc.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from(fileContent),
        },
        parent: 'e2e-test',
        index_for_search: 'true',
      },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();

    // Verify response structure
    expect(data.id).toBeDefined();
    expect(data.filename).toBe('test-doc.md');
    expect(data.storage_key).toBeDefined();
    expect(data.indexed_for_search).toBe(true);
    expect(data.file_size).toBeGreaterThan(0);
    expect(data.mime_type).toBe('text/markdown');
    expect(data.metadata?.file_hash).toBeDefined();

    console.log(`✅ Document uploaded: ${data.id}`);
    console.log(`   Storage key: ${data.storage_key}`);
    console.log(`   Indexed for search: ${data.indexed_for_search}`);
  });

  test('POST /docs/upload - text file without ChromaDB indexing (S3 only)', async ({ request }) => {
    const fileContent = `# S3-Only Document\n\nThis document is stored only in S3, not indexed.\nCreated at: ${new Date().toISOString()}`;

    const response = await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 's3-only-doc.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from(fileContent),
        },
        parent: 'e2e-test',
        index_for_search: 'false', // Skip ChromaDB indexing
      },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();

    expect(data.id).toBeDefined();
    expect(data.filename).toBe('s3-only-doc.md');
    expect(data.storage_key).toBeDefined();
    expect(data.indexed_for_search).toBe(false);
    expect(data.file_size).toBeGreaterThan(0);

    console.log(`✅ S3-only document uploaded: ${data.id}`);
  });

  test('POST /docs/upload - binary file (PDF simulation)', async ({ request }) => {
    // Simulate a PDF file with binary content
    const pdfHeader = '%PDF-1.4\n%âãÏÓ\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF';
    const binaryContent = Buffer.from(pdfHeader, 'binary');

    const response = await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 'test-document.pdf',
          mimeType: 'application/pdf',
          buffer: binaryContent,
        },
        parent: 'e2e-test',
        index_for_search: 'true', // Will be stored in S3 only since it's binary
      },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();

    expect(data.id).toBeDefined();
    expect(data.filename).toBe('test-document.pdf');
    expect(data.storage_key).toBeDefined();
    expect(data.mime_type).toBe('application/pdf');
    // Binary files can't be indexed in ChromaDB
    expect(data.indexed_for_search).toBe(false);

    console.log(`✅ Binary document uploaded: ${data.id}`);
  });

  test('GET /docs - list documents', async ({ request }) => {
    // First upload a document
    await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 'list-test-doc.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# List Test Document'),
        },
        parent: 'e2e-list-test',
      },
    });

    // List documents
    const response = await request.get(`${API_BASE}/api/v1/docs`, {
      params: {
        parent: 'e2e-list-test',
        limit: 10,
      },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();

    expect(data.documents).toBeDefined();
    expect(Array.isArray(data.documents)).toBeTruthy();
    expect(data.total).toBeGreaterThanOrEqual(1);

    console.log(`✅ Listed ${data.documents.length} documents`);
  });

  test('GET /docs/{id} - retrieve document by ID', async ({ request }) => {
    // First upload a document
    const uploadResponse = await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 'retrieve-test-doc.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# Retrieve Test\n\nThis document tests retrieval.'),
        },
      },
    });

    const uploadData = await uploadResponse.json();
    const docId = uploadData.id;

    // Retrieve the document
    const response = await request.get(`${API_BASE}/api/v1/docs/${docId}`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.id).toBe(docId);
    expect(data.filename).toBe('retrieve-test-doc.md');
    expect(data.storage_key).toBeDefined();

    console.log(`✅ Retrieved document: ${docId}`);
  });
});

test.describe('Spec Documents - Session Association', () => {
  let sessionId: string;

  test.beforeAll(async ({ request }) => {
    // Create a spec session for document association
    const response = await request.post(`${API_BASE}/api/v1/spec/sessions`, {
      data: {
        name: 'Document Test Spec',
        description: 'Testing document upload for spec sessions',
      },
    });
    const data = await response.json();
    sessionId = data.id || data.session_id;
    console.log(`Created spec session: ${sessionId}`);
  });

  test('POST /spec-docs/upload - upload document for spec session', async ({ request }) => {
    const fileContent = `# Spec Context Document\n\nThis document provides context for the spec.\nCreated at: ${new Date().toISOString()}`;

    const response = await request.post(`${API_BASE}/api/v1/spec-docs/upload`, {
      multipart: {
        file: {
          name: 'spec-context.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from(fileContent),
        },
        session_id: sessionId,
        document_type: 'supporting',
        notes: 'E2E test document',
      },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();

    expect(data.id).toBeDefined();
    expect(data.original_filename).toBe('spec-context.md');
    expect(data.storage_key).toBeDefined();
    expect(data.sessions).toBeDefined();
    expect(data.sessions.length).toBeGreaterThan(0);
    expect(data.sessions[0].session_id).toBe(sessionId);
    expect(data.sessions[0].role).toBe('supporting');

    console.log(`✅ Spec document uploaded: ${data.id}`);
    console.log(`   Associated with session: ${sessionId}`);
  });

  test('GET /spec-docs/session/{session_id} - list session documents', async ({ request }) => {
    // First upload a document for the session
    await request.post(`${API_BASE}/api/v1/spec-docs/upload`, {
      multipart: {
        file: {
          name: 'session-list-test.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# Session List Test'),
        },
        session_id: sessionId,
        document_type: 'reference',
      },
    });

    // List documents for the session
    const response = await request.get(`${API_BASE}/api/v1/spec-docs/session/${sessionId}`);

    expect(response.ok()).toBeTruthy();
    const data = await response.json();

    expect(data.documents).toBeDefined();
    expect(Array.isArray(data.documents)).toBeTruthy();
    expect(data.summary).toBeDefined();
    expect(data.summary.session_id).toBe(sessionId);
    expect(data.summary.total_documents).toBeGreaterThanOrEqual(1);

    console.log(`✅ Session has ${data.summary.total_documents} documents`);
    console.log(`   Primary: ${data.summary.primary_count}`);
    console.log(`   Supporting: ${data.summary.supporting_count}`);
    console.log(`   Reference: ${data.summary.reference_count}`);
  });

  test('GET /spec-docs/{id}/download - download spec document', async ({ request }) => {
    // First upload a document
    const uploadResponse = await request.post(`${API_BASE}/api/v1/spec-docs/upload`, {
      multipart: {
        file: {
          name: 'download-test.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# Download Test\n\nThis tests the download endpoint.'),
        },
        session_id: sessionId,
      },
    });

    const uploadData = await uploadResponse.json();
    const docId = uploadData.id;

    // Download the document
    const response = await request.get(`${API_BASE}/api/v1/spec-docs/${docId}/download`);

    expect(response.ok()).toBeTruthy();
    expect(response.headers()['content-type']).toContain('text/markdown');

    const content = await response.text();
    expect(content).toContain('Download Test');

    console.log(`✅ Downloaded document: ${docId}`);
  });

  test('DELETE /spec-docs/{id} - soft delete document', async ({ request }) => {
    // First upload a document
    const uploadResponse = await request.post(`${API_BASE}/api/v1/spec-docs/upload`, {
      multipart: {
        file: {
          name: 'delete-test.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# Delete Test'),
        },
        session_id: sessionId,
      },
    });

    const uploadData = await uploadResponse.json();
    const docId = uploadData.id;

    // Soft delete the document
    const deleteResponse = await request.delete(`${API_BASE}/api/v1/spec-docs/${docId}`);
    expect(deleteResponse.status()).toBe(204);

    // Verify it's marked as deleted
    const getResponse = await request.get(`${API_BASE}/api/v1/spec-docs/${docId}`);
    const getData = await getResponse.json();
    expect(getData.is_deleted).toBe(true);
    expect(getData.deleted_at).toBeDefined();

    console.log(`✅ Soft deleted document: ${docId}`);
  });

  test('POST /spec-docs/{id}/associate - associate document with another session', async ({ request }) => {
    // Create another session
    const sessionResponse = await request.post(`${API_BASE}/api/v1/spec/sessions`, {
      data: { name: 'Second Session for Association Test' },
    });
    const sessionData = await sessionResponse.json();
    const secondSessionId = sessionData.id || sessionData.session_id;

    // First upload a document to first session
    const uploadResponse = await request.post(`${API_BASE}/api/v1/spec-docs/upload`, {
      multipart: {
        file: {
          name: 'associate-test.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# Association Test'),
        },
        session_id: sessionId,
      },
    });

    const uploadData = await uploadResponse.json();
    const docId = uploadData.id;

    // Associate with second session
    const associateResponse = await request.post(`${API_BASE}/api/v1/spec-docs/${docId}/associate`, {
      data: {
        session_id: secondSessionId,
        role: 'reference',
        notes: 'Shared document for reference',
      },
    });

    expect(associateResponse.ok()).toBeTruthy();
    const data = await associateResponse.json();

    // Should now be associated with both sessions
    expect(data.sessions.length).toBe(2);
    const sessionIds = data.sessions.map((s: { session_id: string }) => s.session_id);
    expect(sessionIds).toContain(sessionId);
    expect(sessionIds).toContain(secondSessionId);

    console.log(`✅ Document ${docId} associated with ${data.sessions.length} sessions`);
  });
});

test.describe('S3 Storage Verification', () => {
  test('Verify storage_key format follows S3 path convention', async ({ request }) => {
    const response = await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 'storage-path-test.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# Storage Path Test'),
        },
      },
    });

    const data = await response.json();

    // Storage key should follow pattern: documents/{uuid}.{ext}
    expect(data.storage_key).toMatch(/^documents\/[a-f0-9-]{36}\.md$/);

    console.log(`✅ Storage key format verified: ${data.storage_key}`);
  });

  test('Verify file hash is calculated', async ({ request }) => {
    const content = '# Hash Test Document\n\nTesting SHA-256 hash calculation.';
    const response = await request.post(`${API_BASE}/api/v1/docs/upload`, {
      multipart: {
        file: {
          name: 'hash-test.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from(content),
        },
      },
    });

    const data = await response.json();

    // File hash should be a 64-character SHA-256 hex string
    expect(data.metadata?.file_hash).toBeDefined();
    expect(data.metadata?.file_hash).toMatch(/^[a-f0-9]{64}$/);

    console.log(`✅ File hash verified: ${data.metadata?.file_hash?.substring(0, 16)}...`);
  });
});
