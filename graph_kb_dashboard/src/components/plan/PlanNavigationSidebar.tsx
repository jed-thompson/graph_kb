'use client';

import { CheckCircle, Circle, Loader2, AlertCircle, Pause, RotateCcw, Save } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PLAN_PHASES } from '@/lib/store/planStore';
import type { PlanPhaseId } from '@/lib/store/planStore';
import type { WorkflowStatusValue } from '@/types/workflow';

interface PlanNavigationSidebarProps {
    sessionId: string | null;
    sessionName?: string;
    currentPhase: PlanPhaseId;
    phases: Record<PlanPhaseId, 'pending' | 'in_progress' | 'complete' | 'error'>;
    workflowStatus: WorkflowStatusValue;
    budget: {
        remainingLlmCalls: number;
        tokensUsed: number;
        maxLlmCalls: number;
        maxTokens: number;
    };
    onPhaseClick: (phase: PlanPhaseId) => void;
    onResumeSession?: () => void;
    onSaveAndClose?: () => void;
}

const PHASE_LABELS: Record<PlanPhaseId, string> = {
    context: 'Context',
    research: 'Research',
    planning: 'Planning',
    orchestrate: 'Orchestrate',
    assembly: 'Assembly',
};

function PhaseStatusIcon({ status }: { status: string }) {
    switch (status) {
        case 'complete':
            return <CheckCircle className="h-3.5 w-3.5 text-green-500" />;
        case 'in_progress':
            return <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />;
        case 'error':
            return <AlertCircle className="h-3.5 w-3.5 text-red-500" />;
        default:
            return <Circle className="h-3.5 w-3.5 text-gray-300 dark:text-gray-600" />;
    }
}

export function PlanNavigationSidebar({
    sessionId,
    sessionName,
    currentPhase,
    phases,
    workflowStatus,
    budget,
    onPhaseClick,
    onResumeSession,
    onSaveAndClose,
}: PlanNavigationSidebarProps) {
    const completedCount = Object.values(phases).filter((s) => s === 'complete').length;
    const budgetPct = budget.maxLlmCalls > 0
        ? Math.round((budget.remainingLlmCalls / budget.maxLlmCalls) * 100)
        : 100;

    return (
        <div className="flex flex-col h-full border-l border-border bg-card/30 w-64">
            {/* Header */}
            <div className="px-4 py-3 border-b border-border">
                <h3 className="text-sm font-medium truncate">{sessionName ?? 'Plan Session'}</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                    {completedCount}/{PLAN_PHASES.length} phases complete
                </p>
            </div>

            {/* Budget indicator */}
            <div className="px-4 py-3 border-b border-border">
                <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="text-muted-foreground">Budget</span>
                    <span className={cn(budgetPct < 20 && 'text-red-500')}>
                        {budget.remainingLlmCalls} calls left
                    </span>
                </div>
                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                        className={cn(
                            'h-full rounded-full transition-all',
                            budgetPct > 50 ? 'bg-green-500' : budgetPct > 20 ? 'bg-amber-500' : 'bg-red-500',
                        )}
                        style={{ width: `${budgetPct}%` }}
                    />
                </div>
            </div>

            {/* Phase summary cards */}
            <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
                {PLAN_PHASES.map((phaseId) => {
                    const status = phases[phaseId];
                    const isCurrent = currentPhase === phaseId;
                    return (
                        <button
                            key={phaseId}
                            onClick={() => onPhaseClick(phaseId)}
                            className={cn(
                                'w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors text-left',
                                isCurrent && 'bg-primary/10 text-primary font-medium',
                                !isCurrent && 'hover:bg-muted/50 text-muted-foreground',
                                status === 'complete' && !isCurrent && 'text-foreground/70',
                            )}
                        >
                            <PhaseStatusIcon status={status} />
                            <span>{PHASE_LABELS[phaseId]}</span>
                        </button>
                    );
                })}
            </div>

            {/* Action buttons */}
            <div className="px-3 py-3 border-t border-border space-y-2">
                {onResumeSession && workflowStatus !== 'running' && (
                    <button
                        onClick={onResumeSession}
                        className="flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                    >
                        <RotateCcw className="h-4 w-4" />
                        Resume
                    </button>
                )}
                {onSaveAndClose && (
                    <button
                        onClick={onSaveAndClose}
                        className="flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm border border-border hover:bg-muted/50 transition-colors text-muted-foreground"
                    >
                        <Pause className="h-4 w-4" />
                        Save & Close
                    </button>
                )}
            </div>
        </div>
    );
}

export default PlanNavigationSidebar;
