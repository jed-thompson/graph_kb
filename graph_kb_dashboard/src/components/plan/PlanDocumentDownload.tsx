'use client';

import React, { useCallback, useState, useMemo } from 'react';
import { Download, FileText, Layers, CheckCircle, AlertTriangle } from 'lucide-react';
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
}

async function fetchArtifactAndDownload(
  sessionId: string,
  artifactKey: string,
  filename: string,
) {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';
  const url = `${baseUrl}/api/v1/plan/sessions/${sessionId}/artifacts/${artifactKey}`;
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

  // Group entries by major section prefix (e.g. "5.1 Auth" -> "Section 5")
  const groupedEntries = useMemo(() => {
    if (!manifestEntries) return {};
    const grouped: Record<string, DocumentManifestEntry[]> = {};
    manifestEntries.forEach(entry => {
      const match = entry.specSection?.match(/^(\d+)(?:\.\d+)*\s+(.*)/);
      const groupName = match ? `Section ${match[1]}` : 'Other Documents';
      if (!grouped[groupName]) grouped[groupName] = [];
      grouped[groupName].push(entry);
    });
    return grouped;
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

  // Dynamic manifest mode
  if (manifestEntries && manifestEntries.length > 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
          <CheckCircle className="h-5 w-5" />
          <span className="text-sm font-medium">
            Plan completed — {manifestEntries.filter(e => e.status === 'final').length}/{manifestEntries.length} documents
          </span>
        </div>

        {/* Composed index at top */}
        <div className="flex gap-2">
          {composedIndexUrl && (
            <Button
              onClick={() => handleDownload(composedIndexUrl, `${specName || 'plan'}-index.md`, 'index')}
              disabled={downloading !== null}
              className="flex-1 justify-start gap-3 h-10 bg-blue-500 hover:bg-blue-600 text-white"
            >
              <Layers className="w-4 h-4" />
              <span className="font-medium">
                {downloading === 'index' ? 'Downloading...' : 'Download Index'}
              </span>
            </Button>
          )}
          <Button
            onClick={handleDownloadAll}
            disabled={downloading !== null}
            variant="outline"
            className="flex-1 justify-start gap-3 h-10 border-blue-500 text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20"
          >
            <Download className="w-4 h-4" />
            <span className="font-medium">
              {downloading === 'all' ? 'Downloading All...' : 'Download All'}
            </span>
          </Button>
        </div>

        {/* Grouped deliverables */}
        <div className="flex flex-col gap-4 max-h-80 overflow-y-auto pr-2">
          {Object.entries(groupedEntries).map(([groupName, entries]) => (
            <div key={groupName} className="space-y-1.5">
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
                {groupName}
              </h4>
              {entries.map((entry) => (
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
          ))}
        </div>
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
