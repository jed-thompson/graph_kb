'use client';

import { useState, useRef, useEffect } from 'react';
import { CheckCircle, AlertCircle, Circle, Loader2, Trash2, RotateCcw, Map, Pencil, Check, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { PlanSessionSummary } from '@/lib/api/planSessions';
import { PlanSessionDetailsDialog } from './PlanSessionDetailsDialog';

// ── Types ───────────────────────────────────────────────────────

interface PlanSessionListContentProps {
  sessions: PlanSessionSummary[];
  loading: boolean;
  error: string | null;
  onResume: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onRename: (sessionId: string, newName: string) => void;
  onRetry?: () => void;
}

// ── Helpers ─────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
          <CheckCircle className="h-3 w-3" /> Completed
        </span>
      );
    case 'running':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          <Loader2 className="h-3 w-3 animate-spin" /> Running
        </span>
      );
    case 'paused':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          Paused
        </span>
      );
    case 'error':
    case 'budget_exhausted':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
          <AlertCircle className="h-3 w-3" /> Error
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
          <Circle className="h-3 w-3" /> Idle
        </span>
      );
  }
}

function getDisplayStatus(session: PlanSessionSummary): string {
  if (session.completed_phases?.assembly) {
    return 'completed';
  }
  if (session.workflow_status === 'running') {
    const ageMs = Date.now() - new Date(session.updated_at).getTime();
    const isStaleRunning = ageMs > 10 * 60 * 1000;
    if (isStaleRunning) {
      return 'paused';
    }
  }
  return session.workflow_status ?? 'unknown';
}

function truncateId(id: string): string {
  return `${id.slice(0, 8)}…`;
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

const ALL_PHASES = ['context', 'research', 'planning', 'orchestrate', 'assembly'] as const;

function PhaseProgressDots({ completedPhases }: { completedPhases: Record<string, boolean> }) {
  return (
    <div className="flex gap-1">
      {ALL_PHASES.map((p) => (
        <div
          key={p}
          className={cn(
            'w-2 h-2 rounded-full',
            completedPhases[p] ? 'bg-green-500' : 'bg-gray-200 dark:bg-gray-700',
          )}
          title={p}
        />
      ))}
    </div>
  );
}

// ── Editable Plan Name ──────────────────────────────────────────

function EditablePlanName({
  name,
  sessionId,
  onRename,
}: {
  name: string;
  sessionId: string;
  onRename: (sessionId: string, newName: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  // Sync draft when parent name changes (e.g. after successful rename)
  useEffect(() => {
    if (!editing) setDraft(name);
  }, [name, editing]);

  const save = () => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== name) {
      onRename(sessionId, trimmed);
    } else {
      setDraft(name);
    }
    setEditing(false);
  };

  const cancel = () => {
    setDraft(name);
    setEditing(false);
  };

  if (editing) {
    return (
      <span className="flex items-center gap-1">
        <Input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') cancel();
          }}
          className="h-6 text-sm font-medium px-1 py-0 w-48"
        />
        <button onClick={save} className="p-0.5 hover:bg-green-100 dark:hover:bg-green-900/30 rounded">
          <Check className="h-3 w-3 text-green-600" />
        </button>
        <button onClick={cancel} className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded">
          <X className="h-3 w-3 text-red-500" />
        </button>
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1 group">
      <span className="text-sm font-medium truncate">{name}</span>
      <button
        onClick={() => setEditing(true)}
        className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-muted transition-opacity"
        title="Rename"
      >
        <Pencil className="h-3 w-3 text-muted-foreground" />
      </button>
    </span>
  );
}

// ── Component ───────────────────────────────────────────────────

export function PlanSessionListContent({
  sessions,
  loading,
  error,
  onResume,
  onDelete,
  onRename,
  onRetry,
}: PlanSessionListContentProps) {
  const [detailsSession, setDetailsSession] = useState<PlanSessionSummary | null>(null);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
        <AlertCircle className="h-8 w-8" />
        <p className="text-sm">{error}</p>
        {onRetry && (
          <button onClick={onRetry} className="text-sm text-primary hover:underline">
            Retry
          </button>
        )}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
        <Map className="h-10 w-10" />
        <p className="text-sm font-medium">No plan sessions yet</p>
        <p className="text-xs">Create a new plan from the chat using <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">/plan [name]</code></p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {sessions.map((session) => {
        const completedCount = Object.values(session.completed_phases ?? {}).filter(Boolean).length;
        const displayStatus = getDisplayStatus(session);
        const canResume = displayStatus !== 'completed';
        return (
          <div
            key={session.id}
            className="flex items-center justify-between p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <EditablePlanName
                  name={session.name ?? `Plan ${truncateId(session.id)}`}
                  sessionId={session.id}
                  onRename={onRename}
                />
                <span className="text-xs text-muted-foreground font-mono">
                  {truncateId(session.id)}
                </span>
                <StatusBadge status={displayStatus} />
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <PhaseProgressDots completedPhases={session.completed_phases ?? {}} />
                <span>{completedCount}/5 phases</span>
                <span>{formatRelativeTime(session.updated_at)}</span>
              </div>
            </div>
            <div className="flex items-center gap-1 ml-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDetailsSession(session)}
                className="gap-1.5"
              >
                {displayStatus === 'completed' ? (
                  <>
                    <CheckCircle className="h-3.5 w-3.5" />
                    View
                  </>
                ) : (
                  <>
                    <Circle className="h-3.5 w-3.5" />
                    Details
                  </>
                )}
              </Button>
              {canResume ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onResume(session.id)}
                  className="gap-1.5"
                >
                <RotateCcw className="h-3.5 w-3.5" />
                Resume
                </Button>
              ) : null}
              <button
                onClick={() => onDelete(session.id)}
                className="p-1.5 rounded-md hover:bg-red-100 dark:hover:bg-red-900/30 text-red-500 transition-colors"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        );
      })}

      <PlanSessionDetailsDialog
        open={detailsSession !== null}
        session={detailsSession}
        onOpenChange={(open) => {
          if (!open) {
            setDetailsSession(null);
          }
        }}
        onOpenInChat={onResume}
      />
    </div>
  );
}
