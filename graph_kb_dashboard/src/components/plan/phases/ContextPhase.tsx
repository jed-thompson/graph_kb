'use client';

import { BasePhaseContent } from './BasePhaseContent';
import type { PhaseStatus, ThinkingStep, PlanPhaseInfo, GateType } from '../PlanContext';
import type { PhaseField } from '@shared/websocket-events';

interface ContextPhaseProps {
    status: PhaseStatus;
    phaseInfo: PlanPhaseInfo;
    agentContent?: string;
    thinkingSteps: ThinkingStep[];
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
}

export function ContextPhase({
    status,
    phaseInfo,
    agentContent,
    thinkingSteps,
    result,
    promptData,
    showThinking,
    isSubmitting,
    onToggleThinking,
    onSubmit,
    onNavigateToPhase,
    isViewingPastPhase,
}: ContextPhaseProps) {
    return (
        <BasePhaseContent
            phase="context"
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
    );
}
