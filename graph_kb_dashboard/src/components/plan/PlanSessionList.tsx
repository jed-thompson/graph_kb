'use client';

import { useEffect, useState, useCallback } from 'react';
import { RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import { listPlanSessions, deletePlanSession, renamePlanSession, type PlanSessionSummary } from '@/lib/api/planSessions';
import { PlanSessionListContent } from './PlanSessionListContent';

interface PlanSessionListProps {
    onResume: (sessionId: string) => void;
    onDelete?: (sessionId: string) => void;
    trigger?: React.ReactNode;
}

export function PlanSessionList({ onResume, onDelete, trigger }: PlanSessionListProps) {
    const [sessions, setSessions] = useState<PlanSessionSummary[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);

    const fetchSessions = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await listPlanSessions();
            setSessions(data.sessions);
        } catch {
            setError('Failed to load sessions');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (open) fetchSessions();
    }, [open, fetchSessions]);

    const handleDelete = async () => {
        if (!deleteTargetId) return;
        try {
            await deletePlanSession(deleteTargetId);
            setSessions((prev) => prev.filter((s) => s.id !== deleteTargetId));
            onDelete?.(deleteTargetId);
        } catch {
            // Silently fail
        }
        setDeleteTargetId(null);
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
        <>
            <Dialog open={open} onOpenChange={setOpen}>
                <DialogTrigger asChild>
                    {trigger ?? (
                        <Button variant="outline" size="sm">
                            <RotateCcw className="h-4 w-4 mr-1.5" />
                            Resume Session
                        </Button>
                    )}
                </DialogTrigger>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>Plan Sessions</DialogTitle>
                        <DialogDescription>Resume or delete your plan workflows.</DialogDescription>
                    </DialogHeader>
                    <PlanSessionListContent
                        sessions={sessions}
                        loading={loading}
                        error={error}
                        onResume={(id) => { onResume(id); setOpen(false); }}
                        onDelete={setDeleteTargetId}
                        onRename={handleRename}
                        onRetry={fetchSessions}
                    />
                </DialogContent>
            </Dialog>

            {/* Delete confirmation dialog */}
            <Dialog open={!!deleteTargetId} onOpenChange={() => setDeleteTargetId(null)}>
                <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>Delete Plan Session</DialogTitle>
                        <DialogDescription>
                            Are you sure you want to delete this session? This action cannot be undone.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setDeleteTargetId(null)}>
                            Cancel
                        </Button>
                        <Button variant="destructive" onClick={handleDelete}>
                            Delete
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}

export default PlanSessionList;
