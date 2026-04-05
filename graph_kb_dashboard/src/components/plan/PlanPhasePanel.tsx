'use client';

import { useState, useEffect, useCallback } from 'react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import type { PhaseField, PlanArtifactManifestEntry } from '@shared/websocket-events';
import { PlanContextProvider, PHASE_TITLES, type PhaseStatus, type ThinkingStep, type GateType, type TaskState } from './PlanContext';
import { ResearchPhase, ContextPhase, PlanningPhase, OrchestratePhase, AssemblyPhase } from './phases';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PlanPhasePanelProps {
    sessionId?: string | null;
    phase: PlanPhaseId;
    status: PhaseStatus;
    planContextItems?: Record<string, unknown> | null;
    planArtifacts?: PlanArtifactManifestEntry[];
    /** Transient per-task context from WebSocket events — only non-null during active orchestration task */
    specSection?: string | null;
    specSectionContent?: string | null;
    researchSummary?: string | null;
    /** Completed task artifacts accumulated during orchestration for progressive list */
    completedTaskArtifacts?: PlanArtifactManifestEntry[];
    /** Progressive document manifest from plan.manifest.update events */
    documentManifest?: {
        entries: Array<{
            taskId: string;
            specSection: string;
            status: string;
            tokenCount: number;
            sectionType?: string;
        }>;
        totalDocuments: number;
        totalTokens: number;
    };
    promptData?: {
        type?: GateType;
        fields?: PhaseField[];
        prefilled?: Record<string, unknown>;
        summary?: Record<string, unknown>;
        message?: string;
        options?: Array<{ id: string; label: string }>;
        result?: Record<string, unknown>;
        next_phase?: string;
        completeness_score?: number;
        gaps?: Record<string, unknown> | unknown[];
        clarification_questions?: Record<string, unknown>[];
        suggested_actions?: string[];
        architecture_analysis?: Record<string, unknown>;
    };
    agentContent?: string;
    result?: Record<string, unknown>;
    thinkingSteps: Array<{ timestamp: number; phase: PlanPhaseId; message: string }>;
    onSubmit: (data: Record<string, unknown>) => void;
    onRetry: () => void;
    /** HITL callback to navigate back to a specific phase (triggers backend cascade) */
    onNavigateToPhase?: (targetPhase: string) => void;
    /** Whether the user is viewing a non-active phase */
    isViewingPastPhase?: boolean;
    planTasks?: Record<string, TaskState>;
    circuitBreaker?: {
        triggered: boolean;
        message: string;
    };
}

// ---------------------------------------------------------------------------
// Phase Router Component
// ---------------------------------------------------------------------------

interface PhaseRouterProps {
    phase: PlanPhaseId;
    status: PhaseStatus;
    showThinking: boolean;
    isSubmitting: boolean;
    agentContent?: string;
    thinkingSteps: ThinkingStep[];
    result?: Record<string, unknown>;
    /** Transient per-task context from WebSocket events */
    specSection?: string | null;
    specSectionContent?: string | null;
    researchSummary?: string | null;
    /** Completed task artifacts accumulated during orchestration */
    completedTaskArtifacts?: PlanArtifactManifestEntry[];
    /** Progressive document manifest from plan.manifest.update events */
    documentManifest?: {
        entries: Array<{
            taskId: string;
            specSection: string;
            status: string;
            tokenCount: number;
            sectionType?: string;
        }>;
        totalDocuments: number;
        totalTokens: number;
    };
    promptData?: {
        type?: GateType;
        fields?: PhaseField[];
        prefilled?: Record<string, unknown>;
        summary?: Record<string, unknown>;
        message?: string;
        options?: Array<{ id: string; label: string }>;
        result?: Record<string, unknown>;
        next_phase?: string;
        completeness_score?: number;
        gaps?: Record<string, unknown> | unknown[];
        clarification_questions?: Record<string, unknown>[];
        suggested_actions?: string[];
        architecture_analysis?: Record<string, unknown>;
    };
    onToggleThinking: () => void;
    onSubmit: (data: Record<string, unknown>) => void;
    onNavigateToPhase?: (targetPhase: string) => void;
    isViewingPastPhase?: boolean;
    planTasks?: Record<string, TaskState>;
    circuitBreaker?: {
        triggered: boolean;
        message: string;
    };
}

function PhaseRouter({
    phase,
    status,
    showThinking,
    isSubmitting,
    agentContent,
    thinkingSteps,
    result,
    promptData,
    onToggleThinking,
    onSubmit,
    onNavigateToPhase,
    isViewingPastPhase,
    specSection,
    specSectionContent,
    researchSummary,
    completedTaskArtifacts,
    documentManifest,
    planTasks,
    circuitBreaker,
}: PhaseRouterProps) {
    const phaseInfo = PHASE_TITLES[phase];
    const phaseThinkingSteps = thinkingSteps.filter(s => s.phase === phase);

    // Route to appropriate phase component
    switch (phase) {
        case 'research':
            return (
                <ResearchPhase
                    status={status}
                    agentContent={agentContent}
                    thinkingSteps={phaseThinkingSteps}
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

        case 'context':
            return (
                <ContextPhase
                    status={status}
                    phaseInfo={phaseInfo}
                    agentContent={agentContent}
                    thinkingSteps={phaseThinkingSteps}
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

        case 'planning':
            return (
                <PlanningPhase
                    status={status}
                    phaseInfo={phaseInfo}
                    agentContent={agentContent}
                    thinkingSteps={phaseThinkingSteps}
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

        case 'orchestrate':
            return (
                <OrchestratePhase
                    status={status}
                    phaseInfo={phaseInfo}
                    agentContent={agentContent}
                    thinkingSteps={phaseThinkingSteps}
                    planTasks={planTasks}
                    circuitBreaker={circuitBreaker}
                    result={result}
                    promptData={promptData}
                    showThinking={showThinking}
                    isSubmitting={isSubmitting}
                    onToggleThinking={onToggleThinking}
                    onSubmit={onSubmit}
                    onNavigateToPhase={onNavigateToPhase}
                    isViewingPastPhase={isViewingPastPhase}
                    specSection={specSection}
                    specSectionContent={specSectionContent}
                    researchSummary={researchSummary}
                    completedTaskArtifacts={completedTaskArtifacts}
                    documentManifest={documentManifest}
                />
            );

        case 'assembly':
            return (
                <AssemblyPhase
                    status={status}
                    phaseInfo={phaseInfo}
                    agentContent={agentContent}
                    thinkingSteps={phaseThinkingSteps}
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

        default:
            return null;
    }
}

// ---------------------------------------------------------------------------
// Main Orchestrator Component
// ---------------------------------------------------------------------------

export function PlanPhasePanel({
    sessionId,
    phase,
    status,
    planContextItems,
    planArtifacts,
    promptData,
    agentContent,
    result,
    thinkingSteps,
    onSubmit,
    onRetry,
    onNavigateToPhase,
    isViewingPastPhase,
    planTasks,
    circuitBreaker,
    specSection,
    specSectionContent,
    researchSummary,
    completedTaskArtifacts,
    documentManifest,
}: PlanPhasePanelProps) {
    const [showThinking, setShowThinking] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);

    // Reset submitting state when new promptData arrives or status changes
    useEffect(() => {
        setIsSubmitting(false);
    }, [promptData, status]);

    const handleFormSubmit = useCallback((data: Record<string, unknown>) => {
        setIsSubmitting(true);
        onSubmit(data);
    }, [onSubmit]);

    const handleToggleThinking = useCallback(() => {
        setShowThinking(prev => !prev);
    }, []);

    return (
        <PlanContextProvider
            sessionId={sessionId}
            phase={phase}
            status={status}
            planContextItems={planContextItems}
            planArtifacts={planArtifacts}
            promptData={promptData}
            agentContent={agentContent}
            result={result}
            thinkingSteps={thinkingSteps}
            planTasks={planTasks}
            circuitBreaker={circuitBreaker}
            onSubmit={onSubmit}
            onRetry={onRetry}
        >
            <PhaseRouter
                phase={phase}
                status={status}
                showThinking={showThinking}
                isSubmitting={isSubmitting}
                agentContent={agentContent}
                thinkingSteps={thinkingSteps}
                result={result}
                promptData={promptData}
                onToggleThinking={handleToggleThinking}
                onSubmit={handleFormSubmit}
                specSection={specSection}
                specSectionContent={specSectionContent}
                researchSummary={researchSummary}
                completedTaskArtifacts={completedTaskArtifacts ?? planArtifacts}
                documentManifest={documentManifest}
                planTasks={planTasks}
                circuitBreaker={circuitBreaker}
            />
        </PlanContextProvider>
    );
}

export default PlanPhasePanel;
