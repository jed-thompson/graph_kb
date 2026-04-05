'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import { listPlanSessions, deletePlanSession, renamePlanSession, type PlanSessionSummary } from '@/lib/api/planSessions';
import { PlanSessionListContent } from '@/components/plan/PlanSessionListContent';

const RESUME_STORAGE_KEY = 'graphkb-plan-resume';

export default function PlanPage() {
    const router = useRouter();
    const [sessions, setSessions] = useState<PlanSessionSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<PlanSessionSummary | null>(null);

    const fetchSessions = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await listPlanSessions();
            setSessions(data.sessions);
        } catch {
            setError('Failed to load plan sessions');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchSessions();
    }, [fetchSessions]);

    const handleResume = useCallback(
        (sessionId: string) => {
            localStorage.setItem(RESUME_STORAGE_KEY, sessionId);
            router.push('/chat');
        },
        [router],
    );

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await deletePlanSession(deleteTarget.id);
            setSessions((prev) => prev.filter((s) => s.id !== deleteTarget.id));
        } catch {
            // keep the session in the list
        }
        setDeleteTarget(null);
    };

    const handleRename = async (sessionId: string, newName: string) => {
        try {
            const updated = await renamePlanSession(sessionId, newName);
            setSessions((prev) =>
                prev.map((s) => (s.id === sessionId ? { ...s, name: updated.name, updated_at: updated.updated_at } : s)),
            );
        } catch {
            // keep the original name on failure
        }
    };

    return (
        <div className="flex h-[calc(100vh-2rem)] m-4 bg-background rounded-xl border border-border/50 shadow-sm overflow-hidden">
            <div className="flex-1 flex flex-col min-w-0">
                {/* Header */}
                <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
                    <div>
                        <h2 className="font-semibold text-lg">Plan Sessions</h2>
                        <p className="text-xs text-muted-foreground">Manage your plan workflows</p>
                    </div>
                    <Button onClick={() => router.push('/chat')} className="gap-2">
                        <Plus className="h-4 w-4" />
                        New Plan
                    </Button>
                </div>

                {/* Session list */}
                <div className="flex-1 overflow-auto px-6 py-4">
                    <PlanSessionListContent
                        sessions={sessions}
                        loading={loading}
                        error={error}
                        onResume={handleResume}
                        onDelete={(id) => {
                            const session = sessions.find((s) => s.id === id);
                            setDeleteTarget(session ?? null);
                        }}
                        onRename={handleRename}
                        onRetry={fetchSessions}
                    />
                </div>
            </div>

            {/* Delete confirmation dialog */}
            <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
                <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>Delete Plan Session</DialogTitle>
                        <DialogDescription>
                            Are you sure you want to delete &ldquo;{deleteTarget?.name ?? 'Untitled Plan'}&rdquo;?
                            This action cannot be undone.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setDeleteTarget(null)}>
                            Cancel
                        </Button>
                        <Button variant="destructive" onClick={handleDelete}>
                            Delete
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
