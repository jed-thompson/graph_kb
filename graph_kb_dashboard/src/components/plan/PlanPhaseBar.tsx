'use client';

import { CheckCircle, Circle, Loader2, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PLAN_PHASES } from '@/lib/store/planStore';
import type { PlanPhaseId } from '@/lib/store/planStore';

interface PlanPhaseBarProps {
    currentPhase: PlanPhaseId;
    phases: Record<PlanPhaseId, 'pending' | 'in_progress' | 'complete' | 'error'>;
    overallProgress: number;
    onPhaseClick: (phase: PlanPhaseId) => void;
    onStepForward?: () => void;
    onStepBackward?: (phase: PlanPhaseId) => void;
    /** Index of the first completed phase (for computing previous phase) */
    completedPhases?: Record<PlanPhaseId, boolean>;
    /** Whether the workflow is at an interrupt or actively running */
    isPaused?: boolean;
    /** The phase the user is viewing (null = following backend) */
    viewingPhase?: PlanPhaseId | null;
}

const PHASE_LABELS: Record<PlanPhaseId, string> = {
    context: 'Context',
    research: 'Research',
    planning: 'Planning',
    orchestrate: 'Orchestrate',
    assembly: 'Assembly',
};

const PHASE_COLORS: Record<PlanPhaseId, { bg: string; active: string; text: string }> = {
    context: { bg: 'bg-blue-100 dark:bg-blue-900/30', active: 'bg-blue-500', text: 'text-blue-700 dark:text-blue-300' },
    research: { bg: 'bg-amber-100 dark:bg-amber-900/30', active: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-300' },
    planning: { bg: 'bg-green-100 dark:bg-green-900/30', active: 'bg-green-500', text: 'text-green-700 dark:text-green-300' },
    orchestrate: { bg: 'bg-pink-100 dark:bg-pink-900/30', active: 'bg-pink-500', text: 'text-pink-700 dark:text-pink-300' },
    assembly: { bg: 'bg-purple-100 dark:bg-purple-900/30', active: 'bg-purple-500', text: 'text-purple-700 dark:text-purple-300' },
};

function StatusIcon({ status, className }: { status: string; className?: string }) {
    switch (status) {
        case 'complete':
            return <CheckCircle className={cn("h-4 w-4 text-green-500", className)} />;
        case 'in_progress':
            return <Loader2 className={cn("h-4 w-4 text-blue-500 animate-spin", className)} />;
        case 'error':
            return <AlertCircle className={cn("h-4 w-4 text-red-500", className)} />;
        default:
            return <Circle className={cn("h-4 w-4 text-gray-300 dark:text-gray-600", className)} />;
    }
}

export function PlanPhaseBar({
    currentPhase,
    phases,
    overallProgress,
    onPhaseClick,
    onStepForward,
    onStepBackward,
    completedPhases,
    isPaused = false,
    viewingPhase = null,
}: PlanPhaseBarProps) {
    const currentIndex = PLAN_PHASES.indexOf(currentPhase);

    // Compute previous navigable phase (last completed phase before current)
    const prevPhase: PlanPhaseId | null = (() => {
        if (currentIndex <= 0) return null;
        for (let i = currentIndex - 1; i >= 0; i--) {
            if (completedPhases?.[PLAN_PHASES[i]]) return PLAN_PHASES[i];
        }
        return null;
    })();

    // Compute next phase (first uncompleted phase after current)
    const hasNextPhase = (() => {
        for (let i = currentIndex + 1; i < PLAN_PHASES.length; i++) {
            if (phases[PLAN_PHASES[i]] !== 'complete') return true;
        }
        return false;
    })();

    return (
        <div className="bg-card/50 backdrop-blur-sm border-b border-border">
            {/* Overall progress bar */}
            <div className="h-1 bg-muted">
                <div
                    className="h-full bg-primary transition-all duration-500"
                    style={{ width: `${Math.round(overallProgress * 100)}%` }}
                />
            </div>

            {/* Phase steps */}
            <div className="flex items-center px-4 py-3 gap-0.5">
                {PLAN_PHASES.map((phaseId, index) => {
                    const status = phases[phaseId];
                    const isCurrent = currentPhase === phaseId;
                    const isViewing = viewingPhase === phaseId;
                    const colors = PHASE_COLORS[phaseId];

                    return (
                        <div key={phaseId} className="flex items-center flex-1 min-w-0">
                            <button
                                onClick={() => onPhaseClick(phaseId)}
                                className={cn(
                                    'flex items-center gap-1.5 px-2 py-1.5 rounded-lg transition-all text-sm w-full min-w-0',
                                    isCurrent && colors.bg,
                                    isCurrent && 'ring-2 ring-offset-1 ring-offset-background ring-primary/30 font-medium',
                                    isViewing && !isCurrent && 'ring-2 ring-offset-1 ring-offset-background ring-amber-400/50 bg-amber-50 dark:bg-amber-900/20',
                                    !isCurrent && !isViewing && 'hover:bg-muted/50',
                                    status === 'complete' && !isCurrent && !isViewing && 'opacity-80',
                                )}
                            >
                                <StatusIcon status={status} className="flex-shrink-0" />
                                <span className={cn(
                                    'truncate',
                                    isCurrent ? colors.text : 'text-muted-foreground',
                                    status === 'complete' && 'text-green-700 dark:text-green-400',
                                )}>
                                    {PHASE_LABELS[phaseId]}
                                </span>
                            </button>

                            {index < PLAN_PHASES.length - 1 && (
                                <ChevronRight className={cn(
                                    'h-3.5 w-3.5 mx-0.5 flex-shrink-0',
                                    status === 'complete' ? 'text-green-500' : 'text-gray-300 dark:text-gray-600',
                                )} />
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Prev / Next navigation buttons */}
            {(onStepBackward || onStepForward) && (
                <div className="flex items-center justify-between px-4 pb-3 border-t border-border/50 pt-2">
                    <button
                        onClick={() => prevPhase && onStepBackward?.(prevPhase)}
                        disabled={!prevPhase || isPaused}
                        className={cn(
                            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors',
                            prevPhase && !isPaused
                                ? 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                                : 'text-muted-foreground/40 cursor-not-allowed',
                        )}
                    >
                        <ChevronLeft className="h-4 w-4" />
                        Previous
                    </button>

                    <span className="text-xs text-muted-foreground">
                        {viewingPhase ? `Viewing: ${PHASE_LABELS[viewingPhase]}` : PHASE_LABELS[currentPhase]}
                    </span>

                    <button
                        onClick={() => onStepForward?.()}
                        disabled={!hasNextPhase || isPaused}
                        className={cn(
                            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors',
                            hasNextPhase && !isPaused
                                ? 'text-primary hover:bg-primary/10'
                                : 'text-muted-foreground/40 cursor-not-allowed',
                        )}
                    >
                        Next
                        <ChevronRight className="h-4 w-4" />
                    </button>
                </div>
            )}
        </div>
    );
}

export default PlanPhaseBar;
