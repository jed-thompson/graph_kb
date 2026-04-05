'use client';

import { useState } from 'react';
import { createPortal } from 'react-dom';
import { CollapsibleCard } from '@/components/ui/CollapsibleCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    FileText,
    Eye,
    Loader2,
    X,
    ChevronDown,
    ChevronRight,
} from 'lucide-react';
import { getPlanArtifact } from '@/lib/api/planArtifacts';
import { StructuredContent } from '@/components/chat/StructuredContent';
import type { PlanArtifactManifestEntry } from '@shared/websocket-events';

// ── Types ──────────────────────────────────────────────────────────────

interface GeneratedArtifactsPanelProps {
    artifacts?: PlanArtifactManifestEntry[];
    /** Plan session ID for retrieving blob-stored artifacts on demand. */
    sessionId?: string | null;
}

interface OverlayDoc {
    filename: string;
    content: string;
    loading?: boolean;
    error?: string;
}

// ── Phase Grouping ─────────────────────────────────────────────────────

const PHASE_GROUPS: { prefix: string; label: string }[] = [
    { prefix: 'context/', label: 'Context Gathering' },
    { prefix: 'research/', label: 'Research' },
    { prefix: 'plan/', label: 'Planning' },
    { prefix: 'orchestrate/', label: 'Orchestration' },
    { prefix: 'generate/', label: 'Assembly' },
    { prefix: 'assembly/', label: 'Assembly' },
    { prefix: 'output/', label: 'Assembly' },
    { prefix: 'audit/', label: 'Finalize' },
];

interface PhaseGroup {
    label: string;
    items: PlanArtifactManifestEntry[];
    /** For orchestrate: sub-groups by task ID */
    taskGroups?: Map<string, PlanArtifactManifestEntry[]>;
}

function groupByPhase(artifacts: PlanArtifactManifestEntry[]): PhaseGroup[] {
    const groupMap = new Map<string, PhaseGroup>();

    for (const artifact of artifacts) {
        const key = artifact.key;
        const matchedGroup = PHASE_GROUPS.find(g => key.startsWith(g.prefix));

        let groupLabel = matchedGroup?.label ?? 'Other';
        let groupId = groupLabel;

        // For orchestrate, check if it's a task artifact
        const isOrchestrate = key.startsWith('orchestrate/');
        if (isOrchestrate) {
            groupId = 'orchestrate';
            groupLabel = 'Orchestration';
        }

        if (!groupMap.has(groupId)) {
            groupMap.set(groupId, { label: groupLabel, items: [] });
        }
        groupMap.get(groupId)!.items.push(artifact);
    }

    // For orchestrate, build task sub-groups
    const orchestrateGroup = groupMap.get('orchestrate');
    if (orchestrateGroup) {
        const taskGroups = new Map<string, PlanArtifactManifestEntry[]>();
        const nonTask: PlanArtifactManifestEntry[] = [];

        for (const item of orchestrateGroup.items) {
            const taskMatch = item.key.match(/^orchestrate\/tasks\/([^/]+)\//);
            if (taskMatch) {
                const taskId = taskMatch[1];
                if (!taskGroups.has(taskId)) {
                    taskGroups.set(taskId, []);
                }
                taskGroups.get(taskId)!.push(item);
            } else {
                nonTask.push(item);
            }
        }

        orchestrateGroup.taskGroups = taskGroups;
        orchestrateGroup.items = nonTask;
    }

    return Array.from(groupMap.values());
}

// ── Document Overlay (reuses same pattern as ContextItemsPanel) ────────

function DocumentViewOverlay({
    doc,
    onClose,
}: {
    doc: OverlayDoc | null;
    onClose: () => void;
}) {
    if (!doc) return null;

    return (
        <>
            <div
                className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
                onClick={onClose}
            />
            <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none">
                <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-[95vw] max-w-4xl max-h-[85vh] flex flex-col relative pointer-events-auto">
                    <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
                        <div className="flex items-center gap-3">
                            <FileText className="h-5 w-5 text-primary" />
                            <h2 className="text-lg font-semibold">{doc.filename}</h2>
                        </div>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={onClose}
                            className="text-gray-400 hover:text-gray-600"
                        >
                            <X className="h-5 w-5" />
                        </Button>
                    </div>
                    <div className="flex-1 overflow-auto p-6">
                        {doc.loading ? (
                            <div className="flex items-center justify-center py-12">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                <span className="ml-2 text-sm text-muted-foreground">
                                    Loading artifact...
                                </span>
                            </div>
                        ) : doc.error ? (
                            <div className="flex flex-col items-center justify-center py-12 text-center">
                                <div className="text-destructive mb-3">
                                    <FileText className="h-8 w-8 mx-auto opacity-50" />
                                </div>
                                <p className="text-sm font-medium text-destructive mb-1">
                                    Failed to load artifact
                                </p>
                                <p className="text-xs text-muted-foreground max-w-md break-all">
                                    {doc.error}
                                </p>
                            </div>
                        ) : (
                            <div className="text-sm bg-gray-50 dark:bg-gray-800 p-6 rounded-lg leading-relaxed">
                                <StructuredContent
                                    content={doc.content || 'No content available'}
                                    defaultCollapsed={false}
                                    maxHeight="none"
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </>
    );
}

// ── Artifact Row ───────────────────────────────────────────────────────

function ArtifactRow({ artifact, onView }: {
    artifact: PlanArtifactManifestEntry;
    onView: () => void;
}) {
    // Derive a human-readable label from the key
    const label = artifact.summary || artifact.key.split('/').pop() || artifact.key;

    return (
        <button
            type="button"
            onClick={onView}
            className="w-full flex items-center justify-between gap-2 py-2 px-3 rounded-lg border border-border/50 hover:border-border hover:bg-muted/30 transition-colors group text-left"
        >
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                <FileText className="h-4 w-4 text-primary/70 flex-shrink-0" />
                <span className="text-sm truncate">{label}</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                <Eye className="h-3.5 w-3.5" />
                <span>View</span>
            </div>
        </button>
    );
}

// ── Main Panel ─────────────────────────────────────────────────────────

export function GeneratedArtifactsPanel({ artifacts, sessionId }: GeneratedArtifactsPanelProps) {
    const [overlayDoc, setOverlayDoc] = useState<OverlayDoc | null>(null);
    const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

    if (!artifacts || artifacts.length === 0) return null;

    const groups = groupByPhase(artifacts);

    const toggleGroup = (label: string) => {
        setExpandedGroups(prev => {
            const next = new Set(prev);
            if (next.has(label)) {
                next.delete(label);
            } else {
                next.add(label);
            }
            return next;
        });
    };

    const handleView = async (artifact: PlanArtifactManifestEntry) => {
        const label = artifact.summary || artifact.key.split('/').pop() || artifact.key;
        setOverlayDoc({ filename: label, content: '', loading: true });
        if (!sessionId) {
            setOverlayDoc({ filename: label, content: '', error: 'No session ID available.' });
            return;
        }
        try {
            const result = await getPlanArtifact(sessionId, artifact.key);
            setOverlayDoc({ filename: label, content: result.content });
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Failed to load artifact content.';
            setOverlayDoc({ filename: label, content: '', error: msg });
        }
    };

    return (
        <>
            <CollapsibleCard
                title="Generated Artifacts"
                subtitle="Documents and data produced during this workflow"
                icon={<FileText className="h-4 w-4" />}
                badge={<Badge variant="secondary">{artifacts.length} items</Badge>}
                defaultExpanded={true}
                variant="info"
                size="sm"
            >
                <div className="space-y-3">
                    {groups.map(group => {
                        const isExpanded = expandedGroups.has(group.label);
                        const hasTaskGroups = group.taskGroups && group.taskGroups.size > 0;
                        const totalItems = group.items.length +
                            (hasTaskGroups ? Array.from(group.taskGroups!.values()).reduce((sum, items) => sum + items.length, 0) : 0);

                        return (
                            <div key={group.label}>
                                <button
                                    type="button"
                                    onClick={() => toggleGroup(group.label)}
                                    className="w-full flex items-center gap-2 mb-1.5 text-left"
                                >
                                    {isExpanded
                                        ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                                        : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                                    }
                                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                        {group.label}
                                    </span>
                                    <Badge variant="outline" className="text-[10px] h-4 px-1">
                                        {totalItems}
                                    </Badge>
                                </button>
                                {isExpanded && (
                                    <div className="space-y-1.5 ml-5">
                                        {/* Non-task items */}
                                        {group.items.map(artifact => (
                                            <ArtifactRow
                                                key={artifact.key}
                                                artifact={artifact}
                                                onView={() => handleView(artifact)}
                                            />
                                        ))}
                                        {/* Task sub-groups (orchestrate) */}
                                        {hasTaskGroups && Array.from(group.taskGroups!.entries()).map(([taskId, taskItems]) => (
                                            <div key={taskId} className="mt-2">
                                                <div className="text-[11px] font-medium text-muted-foreground/70 uppercase tracking-wider mb-1 pl-3">
                                                    Task {taskId.slice(0, 8)}
                                                </div>
                                                <div className="space-y-1.5">
                                                    {taskItems.map(artifact => (
                                                        <ArtifactRow
                                                            key={artifact.key}
                                                            artifact={artifact}
                                                            onView={() => handleView(artifact)}
                                                        />
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </CollapsibleCard>

            {createPortal(
                <DocumentViewOverlay
                    doc={overlayDoc}
                    onClose={() => setOverlayDoc(null)}
                />,
                document.body,
            )}
        </>
    );
}
