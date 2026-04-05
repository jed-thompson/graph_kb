// shared/websocket-events.ts
//
// Single source of truth for all WebSocket event types between frontend and backend.
// TypeScript types consumed directly by the frontend; serves as reference for backend Pydantic models.

// ── Shared Types ────────────────────────────────────────────────

/** All possible phase IDs across different workflows */
export type PhaseId = "context" | "review" | "research" | "plan" | "orchestrate" | "completeness" | "generate" | "planning" | "assembly";

/** Phase IDs for the 7-phase spec wizard workflow */
export type SpecWizardPhaseId = "context" | "review" | "research" | "plan" | "orchestrate" | "completeness" | "generate";

/** Phase IDs for the 5-phase plan workflow */
export type PlanWorkflowPhaseId = "context" | "research" | "planning" | "orchestrate" | "assembly";

/**
 * Status of an individual workflow phase.
 * Single source of truth — import from here in all consuming files.
 */
export type PhaseStatusValue = "pending" | "in_progress" | "complete" | "skipped" | "error";

/**
 * Overall workflow status for the entire session.
 */
export type WorkflowStatusValue = "idle" | "pending" | "running" | "paused" | "completed" | "error" | "budget_exhausted" | "rejected";

/**
 * Status of a gate within a workflow.
 */
export type GateStatusValue = "pending" | "in_progress" | "complete" | "skipped" | "blocked";

export interface PhaseField {
  id: string;
  label: string;
  type: "text" | "textarea" | "select" | "searchable_select" | "file" | "multiselect" | "json" | "url_list" | "document_list";
  required: boolean;
  options?: Array<string | { label: string; value: string }>;
  placeholder?: string;
}

// ── Client → Server Events ──────────────────────────────────────

export interface SpecStartEvent {
  type: "spec.start";
  payload: { name: string; description?: string };
}

export interface SpecResumeEvent {
  type: "spec.resume";
  payload: { sessionId: string };
}

export interface SpecPhaseInputEvent {
  type: "spec.phase.input";
  payload: {
    sessionId: string;
    phase: PhaseId;
    data: Record<string, unknown>;
  };
}

export interface SpecNavigateEvent {
  type: "spec.navigate";
  payload: {
    sessionId: string;
    targetPhase: PhaseId;
    confirmCascade?: boolean;
  };
}

export interface SpecPauseEvent {
  type: "spec.pause";
  payload: { sessionId: string };
}

export type ClientSpecEvent =
  | SpecStartEvent
  | SpecResumeEvent
  | SpecPhaseInputEvent
  | SpecNavigateEvent
  | SpecPauseEvent
  | PlanStepForwardEvent
  | PlanStepBackwardEvent
  | PlanReconnectEvent;

// ── Server → Client Events ──────────────────────────────────────

export interface SpecPhasePromptEvent {
  type: "spec.phase.prompt";
  data: {
    sessionId: string;
    phase: PhaseId;
    fields: PhaseField[];
    prefilled?: Record<string, unknown>;
  };
}

export interface SpecPhaseProgressEvent {
  type: "spec.phase.progress";
  data: {
    sessionId: string;
    phase: PhaseId;
    message: string;
    percent: number;
    agentContent?: string;
  };
}

export interface SpecPhaseCompleteEvent {
  type: "spec.phase.complete";
  data: {
    sessionId: string;
    phase: PhaseId;
    result: Record<string, unknown>;
  };
}

export interface SpecCascadeWarningEvent {
  type: "spec.cascade.warning";
  data: {
    sessionId: string;
    affectedPhases: PhaseId[];
  };
}

export interface SpecErrorEvent {
  type: "spec.error";
  data: { message: string; code: string; phase?: PhaseId };
}

export interface SpecCompleteEvent {
  type: "spec.complete";
  data: {
    sessionId: string;
    specDocumentUrl: string;
    storyCardsUrl?: string;
  };
}

// ── Plan Navigation Events ──────────────────────────────────────

export interface PlanStateEvent {
  type: "plan.state";
  data: {
    sessionId: string;
    workflowStatus: WorkflowStatusValue;
    currentPhase: PlanWorkflowPhaseId | null;
    completedPhases: Partial<Record<PlanWorkflowPhaseId, boolean>>;
    budget: {
      remainingLlmCalls: number;
      tokensUsed: number;
      maxLlmCalls: number;
      maxTokens: number;
    };
    artifacts?: PlanArtifactManifestEntry[];
    documentManifest?: DocumentManifest;
    planTasks?: Record<string, {
      id: string;
      name: string;
      status: "pending" | "in_progress" | "critiquing" | "complete" | "failed";
      priority?: string;
      dependencies?: string[];
      events: Array<{ timestamp: number; message: string }>;
      iterationCount?: number;
      agentContent?: string;
      specSection?: string | null;
      specSectionContent?: string | null;
      researchSummary?: string | null;
    }>;
    taskContext?: {
      taskId?: string | null;
      taskName?: string | null;
      specSection?: string | null;
      specSectionContent?: string | null;
      researchSummary?: string | null;
    };
    budgetRecoveryAvailable?: boolean;
    phaseSummaries?: Partial<Record<PlanWorkflowPhaseId, {
      title: string;
      status: "completed" | "in_progress" | "pending" | "error";
      summary?: string;
    }>>;
  };
}

export interface PlanCascadeConfirmEvent {
  type: "plan.cascade.confirm";
  data: {
    sessionId: string;
    targetPhase: PlanWorkflowPhaseId;
    affectedPhases: PlanWorkflowPhaseId[];
    estimatedLlmCalls: number;
    dirtyPhases: PlanWorkflowPhaseId[];
  };
}

export interface PlanPausedEvent {
  type: "plan.paused";
  data: {
    status: "paused";
    message: string;
    sessionId: string;
  };
}

// ── Plan Phase-Level Events ───────────────────────────────────

export interface PlanPhaseProgressEvent {
  type: "plan.phase.progress";
  data: {
    session_id: string;
    phase: PlanWorkflowPhaseId;
    step: string;
    message: string;
    percent: number;
    substep?: string;
    task_id?: string;
    task_progress?: string;
    iteration?: number;
    max_iterations?: number;
    agent_type?: string;
    confidence?: number;
    agentContent?: string;
  };
}

export interface PlanPhaseEnterEvent {
  type: "plan.phase.enter";
  data: {
    session_id: string;
    phase: PlanWorkflowPhaseId;
    expected_steps: number;
  };
}

export interface PlanPhaseCompleteEvent {
  type: "plan.phase.complete";
  data: {
    session_id: string;
    phase: PlanWorkflowPhaseId;
    result_summary?: string;
    result?: Record<string, unknown>;
    duration_s: number;
  };
}

export interface PlanPhasePromptEvent {
  type: "plan.phase.prompt";
  data: {
    sessionId: string;
    phase: PlanWorkflowPhaseId;
    promptType: "form" | "approval" | "phase_review" | "analysis_review";
    interrupt_id?: string;
    task_id?: string;
    fields?: PhaseField[];
    summary?: Record<string, unknown>;
    message?: string;
    options?: Array<{ id: string; label: string }>;
    tasks?: Array<Record<string, unknown>>;
    result?: Record<string, unknown>;
    nextPhase?: string;
  };
}

export interface PlanErrorEvent {
  type: "plan.error";
  data: {
    session_id: string;
    message: string;
    code: string;
    phase?: PlanWorkflowPhaseId;
  };
}

export interface DocumentManifestEntry {
  taskId: string;
  specSection: string;
  downloadUrl: string;
  status: "draft" | "reviewed" | "final" | "failed" | "error" | "missing";
  tokenCount: number;
  filename: string;
  sectionType?: string;
  errorMessage?: string;
}

export interface DocumentManifest {
  specName: string;
  totalDocuments: number;
  totalTokens: number;
  composedIndexUrl: string;
  entries: DocumentManifestEntry[];
}

export interface PlanCompleteEvent {
  type: "plan.complete";
  data: {
    session_id: string;
    spec_document_url: string;
    story_cards_url?: string;
    documentManifest?: DocumentManifest;
  };
}

export interface PlanBudgetWarningEvent {
  type: "plan.budget.warning";
  data: {
    session_id: string;
    budget_remaining_pct: number;
    message: string;
  };
}

// ── Plan Task Events (orchestrate sub-tasks) ─────────────────────

export interface PlanTaskStartEvent {
  type: "plan.task.start";
  data: {
    session_id: string;
    task_id: string;
    task_name: string;
    spec_section?: string;
    spec_section_content?: string;
  };
}

export interface PlanTaskCritiqueEvent {
  type: "plan.task.critique";
  data: {
    session_id: string;
    task_id: string;
    passed: boolean;
    feedback: string;
    task_name?: string;
    score?: number;
    iteration?: number;
  };
}

export interface PlanTaskCompleteEvent {
  type: "plan.task.complete";
  data: {
    session_id: string;
    task_id: string;
    task_name?: string;
    spec_section?: string;
    approved?: boolean;
    artifacts?: Array<{ key: string; summary: string }>;
  };
}

// ── Client → Server Plan Navigation Events ──────────────────────

export interface PlanStepForwardEvent {
  type: "plan.step.forward";
  payload: {
    sessionId: string;
  };
}

export interface PlanStepBackwardEvent {
  type: "plan.step.backward";
  payload: {
    sessionId: string;
    targetPhase: PlanWorkflowPhaseId;
    confirmCascade?: boolean;
  };
}

export interface PlanReconnectEvent {
  type: "plan.reconnect";
  payload: {
    sessionId: string;
  };
}

export type ServerSpecEvent =
  | SpecPhasePromptEvent
  | SpecPhaseProgressEvent
  | SpecPhaseCompleteEvent
  | SpecCascadeWarningEvent
  | SpecErrorEvent
  | SpecCompleteEvent
  | PlanStateEvent
  | PlanCascadeConfirmEvent
  | PlanPausedEvent
  | PlanPhaseEnterEvent
  | PlanPhaseProgressEvent
  | PlanPhaseCompleteEvent
  | PlanPhasePromptEvent
  | PlanErrorEvent
  | PlanCompleteEvent
  | PlanBudgetWarningEvent
  | PlanTaskStartEvent
  | PlanTaskCritiqueEvent
  | PlanTaskCompleteEvent;

// ── Plan Artifact Types ─────────────────────────────────────────

/** A single artifact manifest entry carried in plan events. */
export interface PlanArtifactManifestEntry {
  /** Blob key without session prefix, e.g. "research/full_findings.json" */
  key: string;
  /** Human-readable description from ArtifactRef */
  summary: string;
  size_bytes: number;
  /** ISO timestamp */
  created_at: string;
  /** MIME type: "application/json" | "text/markdown" | "text/plain" */
  content_type: string;
}

// ── Review Analysis Types ───────────────────────────────────────

export interface DocumentComment {
  targetId: string;
  targetType: "field" | "document" | "section";
  comment: string;
  severity: "info" | "warning" | "error";
  suggestion?: string;
}

export interface KnowledgeGap {
  id: string;
  category: "scope" | "technical" | "constraint" | "stakeholder";
  title: string;
  description: string;
  impact: "high" | "medium" | "low";
  questions: string[];
  suggestedAnswers: string[];
}

export interface ReviewAnalysisResult {
  completenessScore: number;
  documentComments: DocumentComment[];
  gaps: KnowledgeGap[];
  suggestedActions: string[];
  summary: string;
  confidenceScore?: number;
}
