'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { GitBranch, Loader2, ArrowDownToLine } from 'lucide-react';
import { useWebSocket } from '@/context/WebSocketContext';
import { useIngestStore } from '@/lib/store/ingestStore';
import { cn } from '@/lib/utils';

interface IngestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onIngest: (data: { repoId: string; url: string }) => void;
  onCancel: () => void;
}

type IngestPhase =
  | 'initializing' | 'cloning' | 'discovering' | 'indexing'
  | 'embedding' | 'building' | 'finalizing';

interface IngestProgress {
  phase: IngestPhase;
  progress: number;
  message: string;
  repoId?: string;
  totalFiles?: number;
  processedFiles?: number;
  totalChunks?: number;
  totalSymbols?: number;
  currentFile?: string;
  processedChunks?: number;
  totalChunksToEmbed?: number;
  failedFiles?: number;
}

const PHASE_LABELS: Record<IngestPhase, string> = {
  initializing: 'Initializing',
  cloning: 'Cloning repository',
  discovering: 'Discovering files',
  indexing: 'Indexing files',
  embedding: 'Generating embeddings',
  building: 'Building graph',
  finalizing: 'Finalizing',
};

export function IngestDialog({
  open,
  onOpenChange,
  onIngest,
  onCancel
}: IngestDialogProps) {
  const context = useWebSocket();
  const ws = context?.ws ?? null;
  const isConnected = context?.isConnected ?? false;

  const [gitUrl, setGitUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState<IngestProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Stable refs so the subscription effect doesn't re-run on every keystroke
  // or when the parent re-renders with a new inline callback.
  const gitUrlRef = useRef(gitUrl);
  gitUrlRef.current = gitUrl;
  const onIngestRef = useRef(onIngest);
  onIngestRef.current = onIngest;

  // Subscribe to progress, complete, and error events via the shared context.
  // Only re-subscribe when the dialog opens/closes or the ws instance changes.
  useEffect(() => {
    if (!open || !ws) return;

    setError(null);

    console.log('[IngestDialog] subscribing to ws events', { open, wsConnected: ws.isConnected });

    const unsubProgress = ws.on('progress', (data: unknown) => {
      const event = data as Record<string, unknown>;
      // Backend wraps payload under event.data; fall back to top-level for compat
      const d = ((event.data ?? event) as Record<string, unknown>);
      setProgress({
        phase: (d.phase || d.step || 'initializing') as IngestPhase,
        progress: (d.progress_percent as number) || 0,
        message: (d.message as string) || '',
        repoId: d.repo_id as string | undefined,
        totalFiles: d.total_files as number | undefined,
        processedFiles: d.processed_files as number | undefined,
        totalChunks: d.total_chunks as number | undefined,
        totalSymbols: d.total_symbols as number | undefined,
        currentFile: d.current_file as string | undefined,
        processedChunks: d.processed_chunks as number | undefined,
        totalChunksToEmbed: d.total_chunks_to_embed as number | undefined,
        failedFiles: d.failed_files as number | undefined,
      });
    });

    const unsubComplete = ws.on('complete', (data: unknown) => {
      const event = data as Record<string, unknown>;
      const d = ((event.data ?? event) as Record<string, unknown>);
      setProgress({
        phase: 'finalizing',
        progress: 100,
        message: 'Ingestion complete!',
      });
      setIsLoading(false);
      setTimeout(() => {
        onIngestRef.current({ repoId: (d.repo_id as string) || '', url: gitUrlRef.current });
      }, 1500);
    });

    const unsubError = ws.on('error', (data: unknown) => {
      const event = data as Record<string, unknown>;
      const d = ((event.data ?? event) as Record<string, unknown>);
      const code = d.code as string | undefined;
      const message = (d.message as string) || 'Failed to ingest repository';
      if (code === 'AUTH_ERROR') {
        setError(`Authentication failed: ${message}`);
      } else if (code === 'CLONE_ERROR') {
        setError(`Clone failed: ${message}`);
      } else {
        setError(message);
      }
      setIsLoading(false);
    });

    return () => {
      console.log('[IngestDialog] unsubscribing from ws events');
      unsubProgress();
      unsubComplete();
      unsubError();
    };
  }, [open, ws]);

  const handleIngest = useCallback(() => {
    if (!gitUrl.trim()) {
      setError('Please enter a repository URL');
      return;
    }

    if (!ws || !isConnected) {
      setError('WebSocket not connected');
      return;
    }

    setIsLoading(true);
    setProgress({ phase: 'initializing', progress: 0, message: 'Connecting...' });
    setError(null);

    ws.startIngestWorkflow(gitUrl, branch || 'main');
  }, [gitUrl, branch, ws, isConnected]);

  const handleCancel = useCallback(() => {
    setIsLoading(false);
    setProgress(null);
    setError(null);
    onCancel();
  }, [onCancel]);

  const handleBackground = useCallback(() => {
    useIngestStore.getState().setBackgroundRepo(gitUrl);
    onOpenChange(false);
  }, [gitUrl, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl w-full">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <GitBranch className="h-5 w-5" />
            <DialogTitle>Ingest Repository</DialogTitle>
          </div>
          <DialogDescription>
            Enter a GitHub repository URL to ingest into the knowledge graph
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Repository URL</label>
            <Input
              placeholder="https://github.com/owner/repo"
              value={gitUrl}
              onChange={(e) => setGitUrl(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Branch</label>
            <Input
              placeholder="main"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              disabled={isLoading}
            />
          </div>
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

        {progress && (
          <div className="space-y-3 pt-4 border border-gray-200 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium capitalize">
                {PHASE_LABELS[progress.phase] ?? progress.phase}
              </span>
              {progress.progress > 0 && (
                <span className="text-sm text-muted-foreground tabular-nums">
                  {Math.round(progress.progress)}%
                </span>
              )}
            </div>

            <Progress
              value={progress.progress > 0 ? progress.progress : undefined}
              className={cn("h-2", progress.progress <= 0 && "animate-pulse")}
            />

            <p className="text-sm text-muted-foreground">
              {progress.message || 'Processing...'}
            </p>

            {/* File & chunk stats */}
            {(progress.totalFiles != null && progress.totalFiles > 0) && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground pt-1 border-t border-gray-100">
                <span>Files: {progress.processedFiles ?? 0} / {progress.totalFiles}{progress.failedFiles ? ` (${progress.failedFiles} failed)` : ''}</span>
                <span>Symbols: {progress.totalSymbols ?? 0}</span>
                {progress.phase === 'embedding' && progress.totalChunksToEmbed != null && progress.totalChunksToEmbed > 0 ? (
                  <span>Embeddings: {progress.processedChunks ?? 0} / {progress.totalChunksToEmbed}</span>
                ) : (
                  <span>Chunks: {progress.totalChunks ?? 0}</span>
                )}
                {progress.currentFile && (
                  <span className="col-span-2 truncate" title={progress.currentFile}>
                    {progress.currentFile}
                  </span>
                )}
              </div>
            )}

            {progress.repoId && (
              <p className="text-xs text-muted-foreground mt-1">
                ID: {progress.repoId}
              </p>
            )}
          </div>
        )}

        <div className="flex justify-between items-center pt-4">
          <div>
            {isLoading && (
              <Button
                variant="ghost"
                onClick={handleBackground}
                className="text-muted-foreground text-sm"
              >
                <ArrowDownToLine className="h-4 w-4 mr-2" />
                Run in Background
              </Button>
            )}
          </div>
          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={handleCancel}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button
              onClick={handleIngest}
              disabled={isLoading || !gitUrl.trim()}
            >
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Processing...
                </>
              ) : (
                'Start Ingestion'
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
