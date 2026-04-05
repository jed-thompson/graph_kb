// Shared workflow types used by plan and review features

import type {
  SpecWizardPhaseId,
  PhaseStatusValue,
  WorkflowStatusValue,
  KnowledgeGap,
} from '@shared/websocket-events';

export type {
  SpecWizardPhaseId,
  PhaseStatusValue,
  WorkflowStatusValue,
  KnowledgeGap,
};

// =============================================================================
// Gate Types
// =============================================================================

/**
 * Kind of human-in-the-loop gate/prompt the backend sends for a phase.
 */
export type GateType = 'form' | 'approval' | 'phase_review' | 'analysis_review';

// =============================================================================
// Unified Phase Types
// =============================================================================

/**
 * Status of a single workflow phase.
 * Carried on message metadata as part of WizardPanelMetadata.
 */
export interface PhaseStatus {
  status: PhaseStatusValue;
  data?: Record<string, unknown>;
  result?: Record<string, unknown>;
}

/**
 * A single thinking/progress step emitted during agent execution.
 * Appended to thinkingSteps on each phase progress event.
 */
export interface ThinkingStep {
  timestamp: number;
  phase: SpecWizardPhaseId;
  message: string;
}

/**
 * Canonical metadata carried on message.metadata.wizardPanel.
 * Single source of truth for all wizard UI state.
 */
export interface WizardPanelMetadata {
  sessionId: string;
  currentPhase: SpecWizardPhaseId;
  phases: Record<SpecWizardPhaseId, PhaseStatus>;
  agentContent?: string;
  thinkingSteps: ThinkingStep[];
}
