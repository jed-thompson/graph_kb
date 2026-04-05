'use client';

import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import { usePlanStore } from '@/lib/store/planStore';
import type { PhaseField, PhaseStatusValue, PlanArtifactManifestEntry } from '@shared/websocket-events';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Re-export shared types for plan components */
export type PhaseStatus = PhaseStatusValue;
export type { GateType } from '@/types/workflow';
import type { GateType } from '@/types/workflow';

export interface ThinkingStep {
    timestamp: number;
    phase: PlanPhaseId;
    message: string;
}

export interface TaskItem {
    id: string;
    name: string;
    description: string;
    agent_type: string;
    priority: string;
    dependencies: string[];
}

export interface TaskState {
    id: string;
    name: string;
    status: 'pending' | 'in_progress' | 'critiquing' | 'complete' | 'failed';
    priority?: string;
    dependencies?: string[];
    events: Array<{ timestamp: number; message: string }>;
    iterationCount?: number;
    /** LLM-generated content for this task, captured from agent_content progress events */
    agentContent?: string;
    /** Task-specific spec section heading, preserved across resume/reconnect */
    specSection?: string | null;
    /** Truncated source-section content shown in the task context panel */
    specSectionContent?: string | null;
    /** Task-specific research summary shown in the task context panel */
    researchSummary?: string | null;
}

export interface PlanPhaseInfo {
    title: string;
    description: string;
}

export interface PlanPanelMetadata {
    sessionId: string;
    currentPhase: PlanPhaseId;
    phases: Record<PlanPhaseId, {
        status: PhaseStatusValue;
        data?: Record<string, unknown> & {
            type?: GateType;
            summary?: Record<string, unknown>;
            message?: string;
            options?: Array<{ id: string, label: string }>;
            completeness_score?: number;
            gaps?: Array<{ id: string; category: string; title: string; description: string; severity: string }>;
            clarification_questions?: Array<{ id: string; question: string; context?: string; suggestedAnswers?: string[] }>;
            suggested_actions?: string[];
            architecture_analysis?: {
                implications?: { systemsToModify?: string[]; newComponentsNeeded?: string[]; integrationPoints?: string[] };
                riskAreas?: Array<{ category: string; description: string; severity: string; mitigation?: string }>;
                dependencies?: { externalSystems?: string[]; libraries?: string[]; services?: string[] };
            };
            context_items?: Record<string, unknown>;
        };
        result?: Record<string, unknown>
    }>;
    agentContent?: string;
    thinkingSteps: Array<{ timestamp: number; phase: PlanPhaseId; message: string }>;
    planContextItems?: Record<string, unknown> | null;
    planArtifacts?: PlanArtifactManifestEntry[];
    budget?: {
        remainingLlmCalls: number;
        tokensUsed: number;
        maxLlmCalls: number;
        maxTokens: number;
    };
    workflowStatus?: string;
    planTasks?: Record<string, TaskState>;
    circuitBreaker?: {
        triggered: boolean;
        message: string;
    };
    /** Progressive document manifest accumulated during orchestration */
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
    /** Transient per-task spec section heading from plan.task.start events */
    specSection?: string | null;
    /** Transient per-task spec section content from plan.task.start events */
    specSectionContent?: string | null;
    /** Transient per-task research summary from plan.phase.progress events */
    researchSummary?: string | null;
}

export interface PlanContextValue {
    sessionId?: string | null;
    // Current phase state
    phase: PlanPhaseId;
    status: PhaseStatus;

    // Phase metadata
    phaseInfo: PlanPhaseInfo;

    // Data from backend
    promptData?: {
        type?: GateType;
        interrupt_id?: string;
        task_id?: string;
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
        tasks?: TaskItem[];
    };
    agentContent?: string;
    result?: Record<string, unknown>;
    thinkingSteps: ThinkingStep[];

    // UI state
    showThinking: boolean;
    isSubmitting: boolean;

    // Persisted context items (available across all phases)
    contextItems?: Record<string, unknown> | null;

    // Accumulated artifact manifest entries (generated artifacts from all phases)
    artifacts?: PlanArtifactManifestEntry[];

    // Actions
    onSubmit: (data: Record<string, unknown>) => void;
    onRetry: () => void;
    toggleThinking: () => void;

    // Orchestrate Task Tracker State
    planTasks?: Record<string, TaskState>;
    circuitBreaker?: {
        triggered: boolean;
        message: string;
    };
}

// ---------------------------------------------------------------------------
// Phase Configuration
// ---------------------------------------------------------------------------

export const PHASE_TITLES: Record<PlanPhaseId, PlanPhaseInfo> = {
    context: {
        title: 'Context Gathering',
        description: 'Provide the context and source materials for your feature specification.',
    },
    research: {
        title: 'Research',
        description: 'The agent is researching your requirements and identifying knowledge gaps.',
    },
    planning: {
        title: 'Planning',
        description: 'Generating a roadmap and plan structure for the specification.',
    },
    orchestrate: {
        title: 'Orchestration',
        description: 'Breaking down tasks, running critique loops, and refining the specification.',
    },
    assembly: {
        title: 'Assembly',
        description: 'Generating final documents and running completeness checks.',
    },
};

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const PlanContext = createContext<PlanContextValue | null>(null);

export function usePlanContext() {
    const ctx = useContext(PlanContext);
    if (!ctx) {
        throw new Error('usePlanContext must be used within a PlanContextProvider');
    }
    return ctx;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface PlanContextProviderProps {
    sessionId?: string | null;
    phase: PlanPhaseId;
    status: PhaseStatus;
    planContextItems?: Record<string, unknown> | null;
    planArtifacts?: PlanArtifactManifestEntry[];
    promptData?: {
        type?: GateType;
        interrupt_id?: string;
        task_id?: string;
        fields?: PhaseField[];
        prefilled?: Record<string, unknown>;
        summary?: Record<string, unknown>;
        message?: string;
        options?: Array<{ id: string; label: string }>;
        completeness_score?: number;
        gaps?: Record<string, unknown> | unknown[];
        clarification_questions?: Record<string, unknown>[];
        suggested_actions?: string[];
        architecture_analysis?: Record<string, unknown>;
        tasks?: TaskItem[];
        session_id?: string;
    };
    agentContent?: string;
    result?: Record<string, unknown>;
    thinkingSteps: ThinkingStep[];
    planTasks?: Record<string, TaskState>;
    circuitBreaker?: {
        triggered: boolean;
        message: string;
    };
    onSubmit: (data: Record<string, unknown>) => void;
    onRetry: () => void;
    children: ReactNode;
}

export function PlanContextProvider({
    sessionId,
    phase,
    status,
    planContextItems,
    planArtifacts,
    promptData,
    agentContent,
    result,
    thinkingSteps,
    planTasks,
    circuitBreaker,
    onSubmit,
    onRetry,
    children,
}: PlanContextProviderProps) {
    const [showThinking, setShowThinking] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);

    // Reset submitting state when new promptData arrives or status changes
    useEffect(() => {
        setIsSubmitting(false);
    }, [promptData, status]);

    const handleFormSubmit = useCallback((data: Record<string, unknown>) => {
        setIsSubmitting(true);
        const submitted = { ...data };
        if (promptData?.interrupt_id && submitted.interrupt_id === undefined) {
            submitted.interrupt_id = promptData.interrupt_id;
        }
        if (promptData?.task_id && submitted.task_id === undefined) {
            submitted.task_id = promptData.task_id;
        }
        onSubmit(submitted);
    }, [onSubmit, promptData]);

    const toggleThinking = useCallback(() => {
        setShowThinking(prev => !prev);
    }, []);

    const storeContextItems = usePlanStore((s) => s.contextItems);
    const storeSessionId = usePlanStore((s) => s.sessionId);
    const isValidUuid = !!storeSessionId && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(storeSessionId);
    const resolvedSessionId = sessionId
        ?? promptData?.session_id
        ?? (isValidUuid ? storeSessionId : null);
    const contextItems = planContextItems ?? storeContextItems;

    const value: PlanContextValue = {
        sessionId: resolvedSessionId,
        phase,
        status,
        phaseInfo: PHASE_TITLES[phase],
        promptData,
        agentContent,
        result,
        thinkingSteps,
        showThinking,
        isSubmitting,
        contextItems,
        artifacts: planArtifacts,
        planTasks,
        circuitBreaker,
        onSubmit: handleFormSubmit,
        onRetry,
        toggleThinking,
    };

    return (
        <PlanContext.Provider value={value}>
            {children}
        </PlanContext.Provider>
    );
}
