'use client';

export interface PlanStatePhaseEntry {
    status: string;
    data?: Record<string, unknown>;
    result?: Record<string, unknown>;
}

interface HydratePlanStateSnapshotArgs {
    existingPhases: Record<string, PlanStatePhaseEntry>;
    data: Record<string, unknown>;
    phaseIds: string[];
    fallbackContextItems?: Record<string, unknown> | null;
}

export interface HydratedPlanStateSnapshot {
    currentPhase: string;
    phases: Record<string, PlanStatePhaseEntry>;
    contextItems: Record<string, unknown> | null;
}

export function hydratePlanStateSnapshot({
    existingPhases,
    data,
    phaseIds,
    fallbackContextItems = null,
}: HydratePlanStateSnapshotArgs): HydratedPlanStateSnapshot {
    const completedPhases = (data.completed_phases as Record<string, boolean> | undefined) || {};
    const currentPhase = (data.current_phase as string | undefined) || '';
    const phaseResults = (data.phase_results as Record<string, unknown> | undefined) || {};
    const contextItems = (data.context_items as Record<string, unknown> | undefined) || fallbackContextItems || null;

    const phases = { ...existingPhases };

    for (const phaseId of phaseIds) {
        const existingPhase = phases[phaseId] || { status: 'pending' };
        const phaseResult = phaseResults[phaseId];
        const nextStatus = completedPhases[phaseId]
            ? 'complete'
            : phaseId === currentPhase
                ? 'in_progress'
                : 'pending';

        phases[phaseId] = {
            ...existingPhase,
            status: nextStatus,
            ...(phaseResult && typeof phaseResult === 'object'
                ? { result: phaseResult as Record<string, unknown> }
                : {}),
        };
    }

    return {
        currentPhase,
        phases,
        contextItems,
    };
}
