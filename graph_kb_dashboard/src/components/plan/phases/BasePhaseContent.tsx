'use client';

import { Card } from '@/components/ui/card';
import { Check, Loader2, AlertTriangle, RefreshCcw, RotateCcw } from 'lucide-react';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import { ThinkingStepsPanel } from '../ThinkingStepsPanel';
import { PhaseInputForm } from '../shared/PhaseInputForm';
import { TaskContextInputForm } from '../shared/TaskContextInputForm';
import { PhaseApprovalForm } from '../shared/PhaseApprovalForm';
import { PhaseReviewForm } from '../shared/PhaseReviewForm';
import { AnalysisReviewForm } from '../shared/AnalysisReviewForm';
import { ContextItemsPanel } from '../shared/ContextItemsPanel';
import type { ContextItems } from '../shared/ContextItemsPanel';
import { GeneratedArtifactsPanel } from '../shared/GeneratedArtifactsPanel';
import type { Gap, ClarificationQuestion, ArchitectureAnalysis } from '../shared/AnalysisReviewForm';
import { usePlanContext } from '../PlanContext';
import { Button } from '@/components/ui/button';
import type { PlanPhaseId } from '@/lib/store/planStore';
import type { PhaseStatus, ThinkingStep, PlanPhaseInfo, GateType, TaskItem } from '../PlanContext';
import type { PhaseField } from '@shared/websocket-events';

interface BasePhaseContentProps {
    phase: PlanPhaseId;
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
        // analysis_review fields
        completeness_score?: number;
        gaps?: Gap[];
        clarification_questions?: ClarificationQuestion[];
        suggested_actions?: string[];
        architecture_analysis?: ArchitectureAnalysis;
        context_items?: ContextItems;
    };
    showThinking: boolean;
    isSubmitting: boolean;
    onToggleThinking: () => void;
    onSubmit: (data: Record<string, unknown>) => void;
    /** HITL callback to navigate back to a specific phase (triggers backend cascade) */
    onNavigateToPhase?: (targetPhase: string) => void;
    /** Whether the user is viewing a non-active phase */
    isViewingPastPhase?: boolean;
}

export function BasePhaseContent({
    phase,
    status,
    phaseInfo,
    agentContent,
    thinkingSteps,
    result,
    promptData,
    // showThinking / onToggleThinking kept in interface for caller compat, no longer used
    isSubmitting,
    onSubmit,
    onNavigateToPhase,
    isViewingPastPhase,
}: BasePhaseContentProps) {
    const { onRetry, contextItems: storeContextItems, artifacts, sessionId } = usePlanContext();

    // Shared context panel — renders when context items are available (persisted across phases)
    // Primary source: planStore (set by usePlanSocket). Fallback: promptData.context_items
    // from message metadata (set by WebSocketContext.tsx event handler).
    const contextItems = storeContextItems ?? (promptData?.context_items as ContextItems | undefined);
    const contextPanel = contextItems ? (
        <ContextItemsPanel contextItems={contextItems} sessionId={sessionId} />
    ) : null;
    const artifactsPanel = artifacts && artifacts.length > 0 ? (
        <GeneratedArtifactsPanel artifacts={artifacts} sessionId={sessionId} />
    ) : null;

    // Phase complete — show result
    if (status === 'complete' && result) {
        const markdown = cleanAIText(typeof result.markdown === 'string'
            ? result.markdown
            : typeof result.summary === 'string'
                ? result.summary
                : JSON.stringify(result, null, 2));

        return (
            <div className="max-w-3xl mx-auto space-y-4">
                <div className="flex items-center gap-2">
                    <Check className="h-5 w-5 text-green-500" />
                    <h2 className="text-xl font-semibold">{phaseInfo.title} Complete</h2>
                </div>
                {contextPanel}
                {artifactsPanel}
                <Card className="p-6">
                    <MarkdownRenderer content={markdown} />
                </Card>
                {isViewingPastPhase && onNavigateToPhase && (
                    <div className="flex justify-center pt-2">
                        <Button
                            variant="outline"
                            onClick={() => onNavigateToPhase(phase)}
                            className="gap-2 text-sm border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20"
                        >
                            <RotateCcw className="h-4 w-4" />
                            Return to This Phase
                        </Button>
                    </div>
                )}
            </div>
        );
    }

    // Phase error — show retry button
    if (status === 'error') {
        const errorMsg = result?.error
            ? String((result.error as Record<string, unknown>).message || result.error)
            : 'An error occurred during this phase.';
        return (
            <div className="max-w-3xl mx-auto space-y-4">
                <div className="flex items-center gap-2">
                    <AlertTriangle className="h-5 w-5 text-destructive" />
                    <h2 className="text-xl font-semibold text-destructive">{phaseInfo.title} Error</h2>
                </div>
                <Card className="p-6 border-red-200 bg-red-50/50 dark:bg-red-950/20 dark:border-red-900">
                    <p className="text-red-600 dark:text-red-400 mb-4 font-medium">
                        Workflow Interrupted or Failed
                    </p>
                    <div className="text-sm bg-red-100 dark:bg-red-900/30 p-3 rounded text-red-800 dark:text-red-200 font-mono mb-4 whitespace-pre-wrap">
                        {errorMsg}
                    </div>
                    <Button onClick={onRetry} variant="outline" className="text-red-600 border-red-200 hover:bg-red-100 dark:text-red-400 dark:border-red-900 dark:hover:bg-red-900/50">
                        <RefreshCcw className="w-4 h-4 mr-2" />
                        Retry Sequence
                    </Button>
                </Card>
            </div>
        );
    }

    // Phase in progress — show agent content + full-width thinking steps
    if (status === 'in_progress' && !promptData) {
        return (
            <div className="w-full min-w-0 space-y-4">
                <div className="flex items-center gap-2">
                    <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
                    <h2 className="text-xl font-semibold">{phaseInfo.title}</h2>
                </div>
                <p className="text-sm text-muted-foreground">{phaseInfo.description}</p>
                {contextPanel}
                {artifactsPanel}
                {agentContent && (
                    <Card className="p-6">
                        <MarkdownRenderer content={cleanAIText(agentContent)} />
                    </Card>
                )}
                <ThinkingStepsPanel steps={thinkingSteps} />
            </div>
        );
    }

    // Optimistic processing state after form submission
    if (isSubmitting) {
        return (
            <div className="w-full min-w-0 space-y-4">
                <div className="flex items-center gap-2">
                    <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
                    <h2 className="text-xl font-semibold">{phaseInfo.title}</h2>
                </div>
                <p className="text-sm text-muted-foreground">{phaseInfo.description}</p>
                {contextPanel}
                {artifactsPanel}
                {agentContent && (
                    <Card className="p-6">
                        <MarkdownRenderer content={cleanAIText(agentContent)} />
                    </Card>
                )}
                <ThinkingStepsPanel steps={thinkingSteps} />
            </div>
        );
    }

    // Phase has prompt — show input form, approval, or phase review
    if (promptData) {
        return (
            <div className="max-w-3xl mx-auto space-y-4">
                {contextPanel}
                {artifactsPanel}
                {agentContent && promptData.type !== 'phase_review' && promptData.type !== 'approval' && (
                    <Card className="p-6">
                        <MarkdownRenderer content={cleanAIText(agentContent)} />
                    </Card>
                )}
                {promptData.type === 'phase_review' ? (
                    <PhaseReviewForm
                        phase={phase}
                        nextPhase={promptData.next_phase || 'next'}
                        result={promptData.result}
                        fields={promptData.fields}
                        message={promptData.message}
                        options={promptData.options}
                        onSubmit={onSubmit}
                        sessionId={sessionId}
                    />
                ) : promptData.type === 'analysis_review' ? (
                    <AnalysisReviewForm
                        phase={phase}
                        completenessScore={promptData.completeness_score || 0}
                        gaps={(
                            Array.isArray(promptData.gaps)
                                ? promptData.gaps
                                : promptData.gaps && typeof promptData.gaps === 'object'
                                    ? Object.values(promptData.gaps)
                                    : []
                        ) as Gap[]}
                        clarificationQuestions={promptData.clarification_questions || []}
                        suggestedActions={promptData.suggested_actions || []}
                        architectureAnalysis={promptData.architecture_analysis as ArchitectureAnalysis | undefined}
                        onSubmit={onSubmit}
                    />
                ) : promptData.type === 'approval' ? (
                    <PhaseApprovalForm
                        phase={phase}
                        title={phaseInfo.title}
                        description={phaseInfo.description}
                        summary={promptData.summary}
                        options={promptData.options}
                        message={promptData.message}
                        tasks={promptData.tasks}
                        onSubmit={onSubmit}
                    />
                ) : (promptData as Record<string, unknown>).type === 'task_context_input' ? (
                    <TaskContextInputForm
                        taskName={(promptData as Record<string, unknown>).task_name as string | undefined}
                        specSection={(promptData as Record<string, unknown>).spec_section as string | undefined}
                        message={(promptData as Record<string, unknown>).message as string | undefined}
                        isSubmitting={isSubmitting}
                        onSubmit={onSubmit}
                        onSkip={() => onSubmit({})}
                    />
                ) : (
                    <PhaseInputForm
                        phase={phase}
                        title={phaseInfo.title}
                        description={phaseInfo.description}
                        fields={promptData.fields || []}
                        prefilled={promptData.prefilled}
                        onSubmit={onSubmit}
                        sessionId={sessionId}
                    />
                )}
            </div>
        );
    }

    // Pending — waiting
    return (
        <div className="max-w-3xl mx-auto text-center py-12">
            <h2 className="text-xl font-semibold text-muted-foreground">{phaseInfo.title}</h2>
            <p className="text-sm text-muted-foreground mt-2">
                This phase will begin once the previous phase is complete.
            </p>
        </div>
    );
}
