'use client';

import React, { useCallback, useState, useMemo } from 'react';
import { Download, FileText, CheckCircle, AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { usePlanStore, type DocumentManifestEntry } from '@/lib/store/planStore';

interface PlanDocumentDownloadProps {
  /** Owning plan session for the message being rendered. */
  sessionId?: string | null;
  /** Dynamic manifest entries from the new WebSocket payload. */
  manifestEntries?: DocumentManifestEntry[];
  /** URL to the composed index document. */
  composedIndexUrl?: string;
  /** Legacy URL for single-document backward compat. */
  specDocumentUrl?: string;
  specName?: string;
  /** When true, renders a neutral "ready for review" header instead of "Plan completed". */
  isPreview?: boolean;
  /** Callback to request revisions — re-enters the assembly phase. */
  onRequestRevisions?: () => void;
}

function buildArtifactUrl(sessionId: string, artifactKey: string): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/api\/v1\/?$/, '') || '';
  const prefix = `specs/${sessionId}/`;
  const keyForUrl = artifactKey.startsWith(prefix) ? artifactKey.slice(prefix.length) : artifactKey;
  return `${baseUrl}/api/v1/plan/sessions/${sessionId}/artifacts/${keyForUrl}`;
}

async function fetchArtifactContent(sessionId: string, artifactKey: string): Promise<string> {
  const url = buildArtifactUrl(sessionId, artifactKey);
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to fetch artifact: ${resp.status}`);
  const json = await resp.json();
  const raw = (json.content as string) ?? '';
  return unwrapJsonDocument(raw);
}

/**
 * If the stored content is a JSON envelope with an `assembled_document` key
 * (caused by the LLM returning JSON instead of raw markdown), extract just
 * the markdown. Otherwise return the content unchanged.
 */
function unwrapJsonDocument(content: string): string {
  const trimmed = content.trim();
  if (!trimmed.startsWith('{')) return content;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === 'object' && typeof parsed.assembled_document === 'string' && parsed.assembled_document.length > 50) {
      return parsed.assembled_document;
    }
  } catch {
    // not JSON — return as-is
  }
  return content;
}

async function fetchArtifactAndDownload(
  sessionId: string,
  artifactKey: string,
  filename: string,
) {
  const url = buildArtifactUrl(sessionId, artifactKey);
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to fetch artifact: ${resp.status}`);
  const json = await resp.json();
  const content: string = json.content ?? '';
  const contentType: string = json.content_type ?? 'text/plain';

  const blob = new Blob([content], { type: contentType });
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
}

function downloadBlob(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

const statusColors: Record<string, string> = {
  final: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  reviewed: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  draft: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  error: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
};

export function PlanDocumentDownload({
  sessionId,
  manifestEntries,
  composedIndexUrl,
  specDocumentUrl,
  specName,
  isPreview,
  onRequestRevisions,
}: PlanDocumentDownloadProps) {
  const [downloading, setDownloading] = useState<string | null>(null);

  const resolveSessionId = useCallback(() => {
    if (sessionId) {
      return sessionId;
    }

    try {
      return usePlanStore.getState().sessionId;
    } catch {
      return null;
    }
  }, [sessionId]);

  const handleDownload = useCallback(async (artifactKey: string, filename: string, id: string) => {
    if (!artifactKey || downloading) return;
    const resolvedSessionId = resolveSessionId();
    if (!resolvedSessionId) return;
    setDownloading(id);
    try {
      await fetchArtifactAndDownload(resolvedSessionId, artifactKey, filename);
    } catch (error) {
      console.error('Download failed:', error);
    } finally {
      setDownloading(null);
    }
  }, [downloading, resolveSessionId]);

  // Sections are listed flat — they're all parts of the same document
  const sortedEntries = useMemo(() => {
    if (!manifestEntries) return [];
    return [...manifestEntries];
  }, [manifestEntries]);

  const handleDownloadAll = useCallback(async () => {
    if (!manifestEntries || downloading) return;
    const resolvedSessionId = resolveSessionId();
    if (!resolvedSessionId) return;

    setDownloading('all');
    try {
      if (composedIndexUrl) {
        await fetchArtifactAndDownload(resolvedSessionId, composedIndexUrl, `${specName || 'plan'}-index.md`);
        await new Promise(r => setTimeout(r, 500));
      }
      for (const entry of manifestEntries) {
        if (entry.downloadUrl && entry.status !== 'failed' && entry.status !== 'error') {
          await fetchArtifactAndDownload(resolvedSessionId, entry.downloadUrl, entry.filename || `${entry.taskId}.md`);
          await new Promise(r => setTimeout(r, 500));
        }
      }
    } catch (error) {
      console.error('Download All failed:', error);
    } finally {
      setDownloading(null);
    }
  }, [manifestEntries, composedIndexUrl, downloading, resolveSessionId, specName]);

  const handleDownloadFullDocument = useCallback(async () => {
    if (!manifestEntries || downloading) return;
    const resolvedSessionId = resolveSessionId();
    if (!resolvedSessionId) return;

    setDownloading('full');
    try {
      // Try to fetch the LLM-assembled document from output/spec.md first
      try {
        const assembled = await fetchArtifactContent(resolvedSessionId, 'output/spec.md');
        if (assembled && assembled.length > 100) {
          downloadBlob(assembled, `${specName || 'specification'}.md`);
          return;
        }
      } catch {
        // output/spec.md not available — fall back to concatenation
      }

      // Fallback: concatenate individual sections
      const parts: string[] = [];
      parts.push(`# ${specName || 'Specification'}\n`);
      for (const entry of manifestEntries) {
        if (entry.status === 'failed' || entry.status === 'error') continue;
        if (!entry.downloadUrl) continue;
        try {
          const content = await fetchArtifactContent(resolvedSessionId, entry.downloadUrl);
          if (content) {
            parts.push(`## ${entry.specSection || entry.taskId}\n\n${content}`);
          }
        } catch {
          parts.push(`## ${entry.specSection || entry.taskId}\n\n*[Could not load content]*`);
        }
      }
      downloadBlob(parts.join('\n\n'), `${specName || 'specification'}.md`);
    } catch (error) {
      console.error('Download Full Document failed:', error);
    } finally {
      setDownloading(null);
    }
  }, [manifestEntries, downloading, resolveSessionId, specName]);

  // Dynamic manifest mode
  if (manifestEntries && manifestEntries.length > 0) {
    return (
      <div className="space-y-3">
        <div className={`flex items-center gap-2 ${isPreview ? 'text-blue-600 dark:text-blue-400' : 'text-green-600 dark:text-green-400'}`}>
          {isPreview ? <FileText className="h-5 w-5" /> : <CheckCircle className="h-5 w-5" />}
          <span className="text-sm font-medium">
            {isPreview
              ? `${manifestEntries.filter(e => e.status === 'final' || e.status === 'reviewed').length}/${manifestEntries.length} documents ready for review`
              : `Plan completed — ${manifestEntries.filter(e => e.status === 'final').length}/${manifestEntries.length} documents`}
          </span>
        </div>

        {/* Primary: Download Full Document */}
        <div className="flex gap-2">
          <Button
            onClick={handleDownloadFullDocument}
            disabled={downloading !== null}
            className="flex-1 justify-start gap-3 h-10 bg-blue-500 hover:bg-blue-600 text-white"
          >
            <Download className="w-4 h-4" />
            <span className="font-medium">
              {downloading === 'full' ? 'Assembling Document...' : 'Download Full Document'}
            </span>
            <span className="ml-auto text-blue-200 text-xs">
              {manifestEntries.reduce((sum, e) => sum + (e.tokenCount || 0), 0).toLocaleString()}t
            </span>
          </Button>
        </div>

        {/* Document sections */}
        <div className="flex flex-col gap-1.5 max-h-80 overflow-y-auto pr-2">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
            Sections ({sortedEntries.length})
          </h4>
          {sortedEntries.map((entry) => (
            <div key={entry.taskId} className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDownload(entry.downloadUrl, entry.filename || `${entry.taskId}.md`, entry.taskId)}
                  disabled={!entry.downloadUrl || downloading !== null}
                  className="flex-1 justify-start gap-2 h-8 text-xs"
                >
                  <Download className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate">
                    {entry.specSection || entry.taskId}
                  </span>
                  <span className="text-muted-foreground ml-auto flex-shrink-0">
                    {entry.tokenCount}t
                  </span>
                </Button>
                <span className={`text-[10px] px-1.5 py-0.5 rounded flex-shrink-0 ${statusColors[entry.status] || ''}`}>
                  {entry.status}
                </span>
                {entry.status === 'failed' || entry.status === 'error' ? (
                  <AlertTriangle className="w-3 h-3 text-red-500 flex-shrink-0" />
                ) : null}
              </div>
              {(entry.status === 'failed' || entry.status === 'error') && entry.errorMessage && (
                <div className="text-[10px] text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/50 p-1.5 rounded border border-red-100 dark:border-red-900 ml-6">
                  {entry.errorMessage}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Request Revisions */}
        {onRequestRevisions && (
          <Button
            onClick={onRequestRevisions}
            variant="outline"
            className="w-full justify-center gap-2 h-9 text-sm border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Request Revisions
          </Button>
        )}
      </div>
    );
  }

  // Legacy single-document mode (backward compat)
  if (specDocumentUrl) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
          <CheckCircle className="h-5 w-5" />
          <span className="text-sm font-medium">Plan workflow completed successfully</span>
        </div>
        <Button
          onClick={() => handleDownload(specDocumentUrl, `${specName || 'plan'}-spec.md`, 'document')}
          disabled={downloading !== null}
          className="w-full justify-start gap-3 h-10 bg-blue-500 hover:bg-blue-600 text-white"
        >
          <FileText className="w-4 h-4" />
          <span className="font-medium">
            {downloading === 'document' ? 'Downloading...' : 'Download Spec Document'}
          </span>
        </Button>
      </div>
    );
  }

  return null;
}
