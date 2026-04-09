'use client';

import { useState } from 'react';

import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { cn } from '@/lib/utils';
import type { PhaseField, PlanArtifactManifestEntry } from '@shared/websocket-events';
import {
    AlertCircle,
    AlertTriangle,
    CheckCircle,
    ChevronDown,
    ChevronRight,
    FileSearch,
    FileText,
    Layers,
    Loader2,
    PlayCircle,
} from 'lucide-react';

import type { GateType, PhaseStatus, PlanPhaseInfo, TaskState, ThinkingStep } from '../PlanContext';
import { TaskContextPanel } from '../shared/TaskContextPanel';
import { BasePhaseContent } from './BasePhaseContent';

interface ManifestEntry {
    taskId: string;
    specSection: string;
    status: string;
    tokenCount: number;
    sectionType?: string;
}

interface DocumentManifestData {
    entries: ManifestEntry[];
    totalDocuments: number;
    totalTokens: number;
}

interface OrchestratePhaseProps {
    status: PhaseStatus;
    phaseInfo: PlanPhaseInfo;
    agentContent?: string;
    thinkingSteps: ThinkingStep[];
    planTasks?: Record<string, TaskState>;
    circuitBreaker?: {
        triggered: boolean;
        message: string;
    };
    result?: Record<string, unknown>;
    promptData?: {
        type?: GateType;
        fields?: PhaseField[];
        prefilled?: Record<string, unknown>;
        summary?: Record<string, unknown>;
        message?: string;
        options?: Array<{ id: string; label: string }>;
        result?: Record<string, unknown>;
        next_phase?: string;
    };
    showThinking: boolean;
    isSubmitting: boolean;
    onToggleThinking: () => void;
    onSubmit: (data: Record<string, unknown>) => void;
    onNavigateToPhase?: (targetPhase: string) => void;
    isViewingPastPhase?: boolean;
    specSection?: string | null;
    specSectionContent?: string | null;
    researchSummary?: string | null;
    completedTaskArtifacts?: PlanArtifactManifestEntry[];
    documentManifest?: DocumentManifestData;
}

function isDeliverableArtifact(artifact: PlanArtifactManifestEntry): boolean {
    return artifact.key.startsWith('orchestrate/tasks/') && artifact.content_type === 'text/markdown';
}

const manifestStatusColors: Record<string, string> = {
    final: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
    reviewed: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
    draft: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
    failed: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
    error: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
};

function DocumentManifestPanel({ manifest }: { manifest: DocumentManifestData }) {
    const [expanded, setExpanded] = useState(true);
    const finalCount = manifest.entries.filter((entry) => entry.status === 'final' || entry.status === 'reviewed').length;

    return (
        <div className="rounded-lg border border-indigo-200 dark:border-indigo-800/40 bg-indigo-50/50 dark:bg-indigo-950/20 overflow-hidden">
            <div
                className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-indigo-100/50 dark:hover:bg-indigo-900/20"
                onClick={() => setExpanded(!expanded)}
            >
                <div className="flex items-center gap-2.5">
                    <Layers className="w-4 h-4 text-indigo-500" />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Document Manifest
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                        {finalCount}/{manifest.totalDocuments} docs | {(manifest.totalTokens / 1000).toFixed(1)}K tokens
                    </span>
                </div>
                <svg
                    className={cn('w-4 h-4 text-slate-400 transition-transform', expanded ? 'rotate-180' : '')}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </div>
            {expanded && (
                <div className="px-4 pb-3 space-y-1.5">
                    {manifest.entries.map((entry) => (
                        <div key={entry.taskId} className="flex items-center justify-between py-1.5 px-2 rounded bg-white/60 dark:bg-slate-800/40">
                            <div className="flex items-center gap-2 min-w-0">
                                <FileText className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                                <span className="text-xs text-slate-700 dark:text-slate-300 truncate">
                                    {entry.specSection || entry.taskId}
                                </span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                <span className="text-[10px] text-slate-500 font-mono">{entry.tokenCount}t</span>
                                <span className={cn('text-[10px] px-1.5 py-0.5 rounded font-medium', manifestStatusColors[entry.status] || '')}>
                                    {entry.status}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function TaskCard({
    task,
    childTasks = [],
}: {
    task: TaskState;
    childTasks?: TaskState[];
}) {
    const [expanded, setExpanded] = useState(false);
    const [showContent, setShowContent] = useState(false);
    const hasChildren = childTasks.length > 0;

    const getStatusIcon = () => {
        switch (task.status) {
            case 'complete':
                return <CheckCircle className="w-4 h-4 text-emerald-500" />;
            case 'critiquing':
                return <FileSearch className="w-4 h-4 text-purple-500 animate-pulse" />;
            case 'in_progress':
                return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
            case 'failed':
                return <AlertCircle className="w-4 h-4 text-red-500" />;
            default:
                return <PlayCircle className="w-4 h-4 text-slate-400" />;
        }
    };

    const getStatusColor = () => {
        switch (task.status) {
            case 'complete':
                return 'border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/5';
            case 'critiquing':
                return 'border-purple-500/30 bg-purple-50 dark:bg-purple-500/5';
            case 'in_progress':
                return 'border-blue-500/30 bg-blue-50 dark:bg-blue-500/5';
            case 'failed':
                return 'border-red-500/30 bg-red-50 dark:bg-red-500/5';
            default:
                return 'border-slate-200 dark:border-slate-700/30 bg-slate-50 dark:bg-slate-800/10 opacity-70';
        }
    };

    const getStatusText = () => {
        switch (task.status) {
            case 'complete':
                return 'Complete';
            case 'critiquing':
                return 'Critiquing';
            case 'in_progress':
                return 'Working';
            case 'failed':
                return 'Failed';
            default:
                return 'Pending';
        }
    };

    return (
        <div className={cn('rounded-lg border overflow-hidden transition-colors duration-300', getStatusColor())}>
            <div
                className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-slate-500/5"
                onClick={() => setExpanded(!expanded)}
            >
                <div className="flex items-center gap-3">
                    {getStatusIcon()}
                    <div>
                        <div className="text-sm font-medium text-slate-800 dark:text-slate-200">{task.name}</div>
                        <div className="text-xs text-slate-500">
                            {task.events.length} event(s) | Iteration: {task.iterationCount || 0}
                            {task.agentContent && <span className="ml-1 text-indigo-500">| Has output</span>}
                            {hasChildren && <span className="ml-1">| {childTasks.length} subtask{childTasks.length === 1 ? '' : 's'}</span>}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-xs font-medium uppercase tracking-wider text-slate-600 dark:text-slate-400">
                        {getStatusText()}
                    </span>
                    <svg
                        className={cn('w-4 h-4 text-slate-400 transition-transform', expanded ? 'rotate-180' : '')}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                    >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                </div>
            </div>

            {expanded && (
                <div className="border-t border-slate-200 dark:border-slate-700/30">
                    {task.events.length > 0 && (
                        <div className="px-4 py-3 bg-slate-100/50 dark:bg-slate-900/50 text-xs text-slate-600 dark:text-slate-400 font-mono space-y-2">
                            {task.events.map((event, idx) => (
                                <div key={idx} className="flex gap-2">
                                    <span className="text-slate-400 dark:text-slate-500 shrink-0">
                                        [{new Date(event.timestamp).toLocaleTimeString()}]
                                    </span>
                                    <span className="break-words">{event.message}</span>
                                </div>
                            ))}
                        </div>
                    )}

                    {hasChildren && (
                        <div className="border-t border-slate-200 dark:border-slate-700/30 px-4 py-3 space-y-2 bg-white/40 dark:bg-slate-900/20">
                            <div className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
                                Subtasks
                            </div>
                            <div className="space-y-2">
                                {childTasks.map((childTask) => (
                                    <TaskCard key={childTask.id} task={childTask} />
                                ))}
                            </div>
                        </div>
                    )}

                    {task.agentContent && (
                        <div className="border-t border-slate-200 dark:border-slate-700/30">
                            <button
                                type="button"
                                className="w-full flex items-center gap-2 px-4 py-2 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/10 transition-colors"
                                onClick={(event) => {
                                    event.stopPropagation();
                                    setShowContent(!showContent);
                                }}
                            >
                                {showContent ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                <FileText className="w-3 h-3" />
                                LLM Output
                            </button>
                            {showContent && (
                                <div className="px-4 pb-3 max-h-80 overflow-y-auto">
                                    <div className="text-sm bg-white dark:bg-slate-900 rounded-lg p-4 border border-slate-200 dark:border-slate-700/30">
                                        <MarkdownRenderer content={task.agentContent} />
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function ComposedDocumentView({ tasks }: { tasks: TaskState[] }) {
    const [expanded, setExpanded] = useState(false);
    const completedWithContent = tasks.filter((task) => task.status === 'complete' && task.agentContent);

    if (completedWithContent.length === 0) {
        return null;
    }

    return (
        <div className="rounded-lg border border-teal-200 dark:border-teal-800/40 bg-teal-50/50 dark:bg-teal-950/20 overflow-hidden">
            <div
                className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-teal-100/50 dark:hover:bg-teal-900/20"
                onClick={() => setExpanded(!expanded)}
            >
                <div className="flex items-center gap-2.5">
                    <FileText className="w-4 h-4 text-teal-500" />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Composed Document
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                        {completedWithContent.length} section{completedWithContent.length !== 1 ? 's' : ''} produced
                    </span>
                </div>
                <svg
                    className={cn('w-4 h-4 text-slate-400 transition-transform', expanded ? 'rotate-180' : '')}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </div>
            {expanded && (
                <div className="px-4 pb-4 max-h-[60vh] overflow-y-auto space-y-4">
                    {completedWithContent.map((task) => (
                        <div key={task.id} className="space-y-1">
                            <div className="flex items-center gap-2 text-xs font-medium text-teal-700 dark:text-teal-400">
                                <CheckCircle className="w-3 h-3" />
                                {task.name}
                            </div>
                            <div className="text-sm bg-white dark:bg-slate-900 rounded-lg p-4 border border-slate-200 dark:border-slate-700/30">
                                <MarkdownRenderer content={task.agentContent!} />
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export function OrchestratePhase({
    status,
    phaseInfo,
    agentContent,
    thinkingSteps,
    planTasks,
    circuitBreaker,
    result,
    promptData,
    showThinking,
    isSubmitting,
    onToggleThinking,
    onSubmit,
    onNavigateToPhase,
    isViewingPastPhase,
    specSection,
    specSectionContent,
    researchSummary,
    completedTaskArtifacts,
    documentManifest,
}: OrchestratePhaseProps) {
    let displayTasks = planTasks ? Object.values(planTasks) : [];

    if (displayTasks.length === 0 && thinkingSteps.length > 0) {
        const syntheticTasksMap = new Map<string, TaskState>();

        thinkingSteps.forEach((step) => {
            let taskId: string | null = null;
            let currentStatus: TaskState['status'] = 'in_progress';
            let name = 'Unknown Task';
            let isUpdate = false;

            if (step.message.startsWith('✓ Completed:') || step.message.startsWith('⚠ Failed:')) {
                isUpdate = true;
                const isApproved = step.message.startsWith('✓');
                name = step.message.replace(/^[✓⚠] (Completed|Failed):/, '').replace('(Unapproved)', '').trim();
                taskId = `synthetic-${name}`;
                currentStatus = isApproved && !step.message.includes('(Unapproved)') ? 'complete' : 'failed';
            } else if (step.phase === 'orchestrate' && step.message.startsWith('✎ Critique [')) {
                isUpdate = true;
                const match = step.message.match(/^✎ Critique \[(.*?)\]:/);
                if (match) {
                    name = match[1];
                    taskId = `synthetic-${name}`;
                    currentStatus = 'critiquing';
                }
            }

            if (isUpdate && taskId) {
                if (!syntheticTasksMap.has(taskId)) {
                    syntheticTasksMap.set(taskId, {
                        id: taskId,
                        name,
                        status: currentStatus,
                        priority: 'medium',
                        dependencies: [],
                        events: [step],
                        iterationCount: currentStatus === 'critiquing' ? 1 : 0,
                    });
                } else {
                    const task = syntheticTasksMap.get(taskId)!;
                    if (task.status !== 'complete' && task.status !== 'failed') {
                        task.status = currentStatus;
                    }
                    if (currentStatus === 'critiquing') {
                        task.iterationCount = (task.iterationCount || 0) + 1;
                    }
                    task.events.push(step);
                }
            }
        });

        displayTasks = Array.from(syntheticTasksMap.values());
    }

    const completedTaskCount = displayTasks.filter((t) => t.status === 'complete').length;
    const deliverables = completedTaskArtifacts?.filter(isDeliverableArtifact) ?? [];
    const totalDeliverableSize = deliverables.reduce((sum, artifact) => sum + artifact.size_bytes, 0);
    const activeTask = displayTasks.find((task) => task.status === 'in_progress' || task.status === 'critiquing');
    const resolvedSpecSection = specSection ?? activeTask?.specSection ?? null;
    const resolvedSpecSectionContent = specSectionContent ?? activeTask?.specSectionContent ?? null;
    const resolvedResearchSummary = researchSummary ?? activeTask?.researchSummary ?? null;

    return (
        <div className="space-y-4">
            {circuitBreaker?.triggered && (
                <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
                    <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                        <div>
                            <h4 className="text-sm font-medium text-red-200">Circuit Breaker Triggered</h4>
                            <p className="mt-1 text-sm text-red-300/[0.85] leading-relaxed">
                                {circuitBreaker.message}
                            </p>
                        </div>
                    </div>
                </div>
            )}

            {!isViewingPastPhase && (
                <TaskContextPanel
                    specSection={resolvedSpecSection}
                    specSectionContent={resolvedSpecSectionContent}
                    researchSummary={resolvedResearchSummary}
                />
            )}

            {documentManifest && documentManifest.entries.length > 0 && (
                <DocumentManifestPanel manifest={documentManifest} />
            )}

            {displayTasks.length > 0 && (
                <div className="space-y-3">
                    <div className="flex items-center justify-between text-sm font-medium text-slate-700 dark:text-slate-300">
                        <h3>Generative Tasks ({displayTasks.length})</h3>
                        <div className="flex items-center gap-4 text-xs text-slate-600 dark:text-slate-500">
                            {deliverables.length > 0 && (
                                <span className="text-emerald-600 dark:text-emerald-400/80 font-mono font-medium">
                                    {(totalDeliverableSize / 1024).toFixed(1)}K gen
                                </span>
                            )}
                            <span className="font-medium">{completedTaskCount} / {displayTasks.length} Completed</span>
                        </div>
                    </div>
                    <div className="space-y-2">
                        {displayTasks.map((task) => (
                            <TaskCard key={task.id} task={task} />
                        ))}
                    </div>
                </div>
            )}

            <ComposedDocumentView tasks={displayTasks} />

            <BasePhaseContent
                phase="orchestrate"
                status={status}
                phaseInfo={phaseInfo}
                agentContent={agentContent}
                thinkingSteps={thinkingSteps}
                result={result}
                promptData={promptData}
                showThinking={showThinking}
                isSubmitting={isSubmitting}
                onToggleThinking={onToggleThinking}
                onSubmit={onSubmit}
                onNavigateToPhase={onNavigateToPhase}
                isViewingPastPhase={isViewingPastPhase}
            />
        </div>
    );
}
