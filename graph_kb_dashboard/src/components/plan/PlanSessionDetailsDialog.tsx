'use client';

import { useEffect, useMemo, useState } from 'react';
import { CheckCircle, FileText, Loader2, RotateCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { ContextItemsPanel, type ContextItems } from '@/components/plan/shared/ContextItemsPanel';
import { GeneratedArtifactsPanel } from '@/components/plan/shared/GeneratedArtifactsPanel';
import { getPlanSession, type PlanSessionDetail, type PlanSessionSummary } from '@/lib/api/planSessions';
import { listPlanArtifacts } from '@/lib/api/planArtifacts';
import type { PlanArtifactManifestEntry } from '@shared/websocket-events';

interface PlanSessionDetailsDialogProps {
  open: boolean;
  session: PlanSessionSummary | null;
  onOpenChange: (open: boolean) => void;
  onOpenInChat?: (sessionId: string) => void;
}

function formatRelativeTime(isoStr: string): string {
  const date = new Date(isoStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function StatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = {
    completed: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    paused: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    running: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    error: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    budget_exhausted: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    rejected: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${classes[status] || classes.rejected}`}>
      {status}
    </span>
  );
}

export function PlanSessionDetailsDialog({
  open,
  session,
  onOpenChange,
  onOpenInChat,
}: PlanSessionDetailsDialogProps) {
  const [detail, setDetail] = useState<PlanSessionDetail | null>(null);
  const [artifacts, setArtifacts] = useState<PlanArtifactManifestEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!open || !session?.id) {
        return;
      }

      setLoading(true);
      setError(null);
      setDetail(null);
      setArtifacts([]);
      try {
        const [sessionDetail, artifactResponse] = await Promise.all([
          getPlanSession(session.id),
          listPlanArtifacts(session.id),
        ]);

        if (cancelled) {
          return;
        }

        setDetail(sessionDetail);
        setArtifacts(artifactResponse.artifacts ?? []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load plan details');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [open, session?.id]);

  const resolvedSession = session ? (detail ?? session) : null;
  const resolvedContextItems = useMemo(
    () => (detail?.context_items ?? null) as ContextItems | null,
    [detail],
  );
  const outputArtifacts = useMemo(
    () => artifacts.filter((artifact) => artifact.key.startsWith('output/')),
    [artifacts],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {resolvedSession?.name || 'Plan Session'}
          </DialogTitle>
          <DialogDescription>
            Review the context, generated artifacts, and outputs captured for this plan workflow.
          </DialogDescription>
        </DialogHeader>

        {!resolvedSession ? null : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 p-4">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={resolvedSession.workflow_status ?? ''} />
                  {resolvedSession.workflow_status === 'completed' ? (
                    <span className="inline-flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
                      <CheckCircle className="h-4 w-4" />
                      Completed
                    </span>
                  ) : null}
                </div>
                <div className="text-xs text-muted-foreground">
                  Updated {formatRelativeTime(resolvedSession.updated_at)}
                </div>
                <div className="text-xs text-muted-foreground font-mono">
                  {resolvedSession.id}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{Object.values(resolvedSession.completed_phases || {}).filter(Boolean).length}/5 phases</Badge>
                <Badge variant="outline">{artifacts.length} artifacts</Badge>
                <Badge variant="outline">{outputArtifacts.length} outputs</Badge>
                {onOpenInChat ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onOpenInChat(resolvedSession.id)}
                    className="gap-1.5"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Open In Chat
                  </Button>
                ) : null}
              </div>
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-16 text-muted-foreground">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Loading plan details...
              </div>
            ) : error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
                {error}
              </div>
            ) : (
              <div className="space-y-4">
                {resolvedContextItems ? (
                  <ContextItemsPanel
                    contextItems={resolvedContextItems}
                    sessionId={resolvedSession.id}
                  />
                ) : (
                  <div className="rounded-lg border border-border/60 bg-muted/20 p-4 text-sm text-muted-foreground">
                    No persisted context items were found for this session.
                  </div>
                )}

                {artifacts.length > 0 ? (
                  <GeneratedArtifactsPanel
                    artifacts={artifacts}
                    sessionId={resolvedSession.id}
                  />
                ) : (
                  <div className="rounded-lg border border-border/60 bg-muted/20 p-4 text-sm text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      No stored workflow artifacts were found for this session.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default PlanSessionDetailsDialog;
