'use client';

import { BasePhaseContent } from './BasePhaseContent';
import { ResearchCompleteView } from './ResearchCompleteView';
import { ResearchInProgressView } from './ResearchInProgressView';
import { extractResearchData } from './researchUtils';
import { usePlanContext } from '../PlanContext';
import { useResearchStore } from '@/lib/store/researchStore';
import type { PhaseStatus, ThinkingStep, PlanPhaseInfo, GateType, TaskItem } from '../PlanContext';
import type { PhaseField } from '@shared/websocket-events';
import type { Gap, ClarificationQuestion, ArchitectureAnalysis } from '../shared/AnalysisReviewForm';
import type { ContextItems } from '../shared/ContextItemsPanel';

interface ResearchPhaseProps {
    status: PhaseStatus;
    phaseInfo: PlanPhaseInfo;
    agentContent?: string;
    thinkingSteps: ThinkingStep[];
    result?: Record<string, unknown>;
    promptData?: {
        session_id?: string;
        type?: GateType;
        fields?: PhaseField[];
        prefilled?: Record<string, unknown>;
        summary?: Record<string, unknown>;
        message?: string;
        tasks?: TaskItem[];
        options?: Array<{ id: string; label: string }>;
        result?: Record<string, unknown>;
        next_phase?: string;
        completeness_score?: number;
        gaps?: Gap[] | Record<string, unknown> | unknown[];
        clarification_questions?: ClarificationQuestion[] | Record<string, unknown>[];
        suggested_actions?: string[];
        architecture_analysis?: ArchitectureAnalysis | Record<string, unknown>;
        context_items?: ContextItems;
    };
    showThinking: boolean;
    isSubmitting: boolean;
    onToggleThinking: () => void;
    onSubmit: (data: Record<string, unknown>) => void;
    onNavigateToPhase?: (targetPhase: string) => void;
    isViewingPastPhase?: boolean;
}

export function ResearchPhase({
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
}: ResearchPhaseProps) {
    const { artifacts, contextItems, sessionId: rawSessionId } = usePlanContext();
    const sessionId = rawSessionId ?? undefined;

    // Research-specific store for real-time updates during in_progress
    const researchStore = useResearchStore();

    // Extract research data from result prop
    const extracted = extractResearchData(result);

    // Merge: prefer store data while in_progress, result data when complete
    const storeCards = researchStore.contextCards as unknown as Record<string, unknown>[];
    const storeGaps = researchStore.gaps as unknown as Record<string, unknown>[];
    const displayContextCards = status === 'in_progress' && storeCards.length > 0
        ? storeCards : extracted.contextCards;
    const displayGaps = status === 'in_progress' && storeGaps.length > 0
        ? storeGaps : extracted.gaps;
    const displayFindings = status === 'in_progress' && researchStore.findings
        ? (researchStore.findings as unknown as Record<string, unknown>)
        : extracted.findings;
    const storeProgress = researchStore.progress as { percent: number; phase: string };
    const displayProgress = status === 'in_progress' && storeProgress.percent > 0
        ? storeProgress : extracted.progress;

    const hasResearchResults = displayContextCards.length > 0
        || displayGaps.length > 0 || displayFindings || result;

    // Complete state with research results — custom rich UI
    if (status === 'complete' && hasResearchResults) {
        return (
            <ResearchCompleteView
                result={result}
                displayContextCards={displayContextCards}
                displayGaps={displayGaps}
                displayFindings={displayFindings}
                contextItems={contextItems}
                artifacts={artifacts}
                sessionId={sessionId}
                onSubmit={onSubmit}
                isViewingPastPhase={isViewingPastPhase}
                onNavigateToPhase={onNavigateToPhase}
            />
        );
    }

    // In-progress with research-specific progress bar and live context cards
    if ((status === 'in_progress' || isSubmitting) && !promptData) {
        return (
            <ResearchInProgressView
                displayProgress={displayProgress}
                displayContextCards={displayContextCards}
                agentContent={agentContent}
                thinkingSteps={thinkingSteps}
                contextItems={contextItems}
                artifacts={artifacts}
                sessionId={sessionId}
            />
        );
    }

    // All other states (prompt, error, pending, submitting-with-prompt) → BasePhaseContent
    return (
        <BasePhaseContent
            phase="research"
            status={status}
            phaseInfo={phaseInfo}
            agentContent={agentContent}
            thinkingSteps={thinkingSteps}
            result={result}
            promptData={promptData as Parameters<typeof BasePhaseContent>[0]['promptData']}
            showThinking={showThinking}
            isSubmitting={isSubmitting}
            onToggleThinking={onToggleThinking}
            onSubmit={onSubmit}
            onNavigateToPhase={onNavigateToPhase}
            isViewingPastPhase={isViewingPastPhase}
        />
    );
}
