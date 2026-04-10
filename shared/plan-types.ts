// shared/plan-types.ts
//
// Single source of truth for plan-specific types shared between frontend and backend.
// Frontend components import from here instead of defining local type aliases.
// Backend Pydantic models should stay consistent with these definitions.

import type { PhaseStatusValue, PlanWorkflowPhaseId } from './websocket-events';

// ── Plan Session Types ──────────────────────────────────────────

/**
 * Summary of a plan session as returned by the list-sessions API.
 * Matches the backend PlanSessionResponse Pydantic model.
 */
export interface PlanSessionSummary {
  id: string;
  name?: string | null;
  description?: string | null;
  user_id?: string;
  status?: string;
  workflow_status?: string | null;
  current_phase?: string | null;
  completed_phases?: Record<string, boolean> | null;
  budget_state?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

/**
 * Full plan session detail including thread_id and extra fields.
 */
export interface PlanSessionDetail extends PlanSessionSummary {
  thread_id?: string | null;
  task_description?: string | null;
  [key: string]: unknown;
}

// ── Task State ──────────────────────────────────────────────────

/**
 * Runtime status of a single orchestrate-phase task.
 * Used by the frontend task tracker and WebSocket plan.state events.
 */
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

// ── Document Manifest ───────────────────────────────────────────

/**
 * A single entry in the document manifest produced during orchestration.
 * Used by PlanDocumentDownload and PhaseApprovalForm.
 */
export interface DocumentManifestEntry {
  taskId: string;
  taskName?: string;
  specSection: string;
  filename: string;
  status: 'draft' | 'reviewed' | 'final' | 'failed' | 'error';
  tokenCount: number;
  downloadUrl: string;
  errorMessage?: string;
}

// ── Phase Status ────────────────────────────────────────────────

/**
 * Status value for a plan workflow phase.
 * Re-exported from websocket-events for convenience.
 */
export type PhaseStatus = PhaseStatusValue;

// Re-export PlanWorkflowPhaseId for convenience
export type { PlanWorkflowPhaseId };
