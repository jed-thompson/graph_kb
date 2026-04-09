'use client';

import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import GraphKBWebSocket, { getWebSocket } from '@/lib/api/websocket';
import { findPlanMessageBySession, getPlanPanelMessageId } from '@/lib/planEventUtils';
import { hydratePlanStateSnapshot } from './planStateHydration';
import type {
  LegacyWSMessage,
  WorkflowProgress,
  WorkflowResult,
  WorkflowError,
  WorkflowPreview,
  V3WorkflowAction,
} from '@/lib/types/api';
import { useChatStore } from '@/lib/store/chatStore';
import { usePlanStore } from '@/lib/store/planStore';
import { useNotificationStore } from '@/lib/store';
import { useIngestStore } from '@/lib/store/ingestStore';

// -----------------------------------------------------------------------------
// Ingestion-specific progress data surfaced to consumers
// -----------------------------------------------------------------------------

export interface IngestionProgress {
  phase: string;
  percent: number;
  files?: number;
  total_files?: number;
  current_file?: string;
  chunks?: number;
  symbols?: number;
}

// -----------------------------------------------------------------------------
// Typed payloads for outgoing WebSocket messages
// -----------------------------------------------------------------------------

interface WSCancelMessage {
  type: 'cancel';
  workflow_id: string;
}

interface WSReconnectMessage {
  type: 'reconnect';
  workflow_id: string;
}

interface WSActionMessage {
  type: 'action';
  action: 'pause' | 'resume';
}

interface WSInputMessage {
  type: 'input';
  payload: { thread_id: string; decision: V3WorkflowAction };
}

export type WSOutgoingMessage =
  | WSCancelMessage
  | WSReconnectMessage
  | WSActionMessage
  | WSInputMessage;

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

/** Safely coerce an unknown socket payload to a plain record for spreading. */
function toRecord(data: unknown): Record<string, unknown> {
  return (typeof data === 'object' && data !== null
    ? data
    : {}) as Record<string, unknown>;
}

/** Type-guard for WSMessage `start` payloads routed through class helpers. */
interface StartPayload {
  workflow_type: string;
  git_url?: string;
  branch?: string;
  query?: string;
  repo_id?: string;
}

// -----------------------------------------------------------------------------
// WebSocket Context Value
// -----------------------------------------------------------------------------

export interface WebSocketContextValue {
  ws: GraphKBWebSocket | null;
  isConnected: boolean;
  connectionError: string | null;
  reconnectAttempts: number;
  maxReconnectAttempts: number;
  connect: () => void;
  disconnect: () => void;
  forceReconnect: () => void;
  sendMessage: (message: LegacyWSMessage | WSOutgoingMessage | Record<string, unknown>) => void;

  /** Current workflow tracking state. */
  currentWorkflow: {
    id: string;
    type: string;
    status: 'idle' | 'running' | 'completed' | 'error' | 'paused';
    progress?: WorkflowProgress;
    result?: WorkflowResult;
    error?: string;
  };
  setCurrentWorkflow: React.Dispatch<
    React.SetStateAction<WebSocketContextValue['currentWorkflow']>
  >;

  /** Latest ingestion-specific progress data (from `progress` messages). */
  ingestionProgress: IngestionProgress | null;

  /** Latest preview received from the backend (from `preview` messages). */
  preview: WorkflowPreview | null;

  /** Latest raw incoming message – useful for components that need full access. */
  lastMessage: Record<string, unknown> | null;

  // -- Typed helper functions ------------------------------------------------

  /** Cancel a running workflow (Req 8.7). */
  sendCancel: (workflowId: string) => void;

  /** Reconnect to resume progress after page refresh (Req 8.8, Req 30.7). */
  sendReconnect: (workflowId: string) => void;

  /** Send pause / resume action for ingestion control (Req 8.9, Req 30.4, Req 30.5). */
  sendAction: (action: 'pause' | 'resume') => void;

  /** Send a user decision for a workflow review (Req 20.1). */
  sendInput: (threadId: string, decision: V3WorkflowAction) => void;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

export function useWebSocket() {
  const context = useContext(WebSocketContext);
  return context;
}

// -----------------------------------------------------------------------------
// WebSocket Provider Component
// -----------------------------------------------------------------------------

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [ws, setWs] = useState<GraphKBWebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [currentWorkflow, setCurrentWorkflow] = useState<
    WebSocketContextValue['currentWorkflow']
  >({
    id: '',
    type: '',
    status: 'idle',
  });
  const [ingestionProgress, setIngestionProgress] =
    useState<IngestionProgress | null>(null);
  const [preview, setPreview] = useState<WorkflowPreview | null>(null);
  const [lastMessage, setLastMessage] = useState<Record<string, unknown> | null>(
    null,
  );

  const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';
  const maxReconnectAttempts = 10;

  // Initialize WebSocket on mount
  useEffect(() => {
    // Use the singleton so dev-mode double-mounts and hot reloads
    // reuse the same underlying connection instead of creating (and
    // immediately tearing down) a new one each time.
    const socket = getWebSocket(wsUrl);

    // -- Handle incoming `progress` messages ----------------------------------
    const unsubProgress = socket.on('progress', (data: unknown) => {
      const progress = data as WorkflowProgress;

      setCurrentWorkflow((prev) => ({
        ...prev,
        status: progress.step === 'paused' ? 'paused' : 'running',
        progress,
      }));

      // Surface ingestion-specific fields
      setIngestionProgress({
        phase: progress.phase ?? progress.step ?? '',
        percent: progress.progress_percent ?? 0,
        files: progress.files ?? progress.processed_files,
        total_files: progress.total_files,
        current_file: progress.current_file,
        chunks: progress.chunks ?? progress.total_chunks,
        symbols: progress.symbols ?? progress.total_symbols,
      });

      setLastMessage({ type: 'progress', ...toRecord(data) });
    });

    // -- Handle incoming `complete` messages -----------------------------------
    const unsubComplete = socket.on('complete', (data: unknown) => {
      const result = data as WorkflowResult;
      setCurrentWorkflow((prev) => ({
        ...prev,
        status: 'completed',
        result,
      }));
      setLastMessage({ type: 'complete', ...toRecord(data) });

      const { backgroundRepoUrl, clearBackgroundRepo } = useIngestStore.getState();
      if (backgroundRepoUrl) {
        useNotificationStore.getState().addNotification({
          type: 'success',
          title: 'Ingestion complete',
          message: backgroundRepoUrl,
          duration: 6000,
        });
        clearBackgroundRepo();
      }
    });

    // -- Handle incoming `error` messages -------------------------------------
    const unsubError = socket.on('error', (data: unknown) => {
      const error = data as WorkflowError;
      setCurrentWorkflow((prev) => ({
        ...prev,
        status: 'error',
        error: error.message || 'Unknown error',
      }));
      setLastMessage({ type: 'error', ...toRecord(data) });

      const { backgroundRepoUrl, clearBackgroundRepo } = useIngestStore.getState();
      if (backgroundRepoUrl) {
        useNotificationStore.getState().addNotification({
          type: 'error',
          title: 'Ingestion failed',
          message: error.message || backgroundRepoUrl,
          duration: 8000,
        });
        clearBackgroundRepo();
      }
    });

    // -- Handle incoming `preview` messages (Req 20.1) ------------------------
    const unsubPreview = socket.on('preview', (data: unknown) => {
      const previewData = data as WorkflowPreview;
      setPreview(previewData);
      setLastMessage({ type: 'preview', ...toRecord(data) });
    });

    // -- Handle incoming `partial` messages -----------------------------------
    const unsubPartial = socket.on('partial', (data: unknown) => {
      setLastMessage({ type: 'partial', ...toRecord(data) });
    });

    // -- Handle incoming `chat_message` messages (feature spec in chat) --
    const unsubChatMessage = socket.on('chat_message', (data: unknown) => {
      setLastMessage({ type: 'chat_message', ...toRecord(data) });
    });

    // -- Handle ALL incoming messages for legacy v2 gate-based wizard --
    // Forwards spec.* and plan.* events to lastMessage and updates chat messages.
    const unsubGenericMessage = socket.on('*', (rawMessage: unknown) => {
      const msg = rawMessage as Record<string, unknown>;
      const msgType = msg.type as string | undefined;

      // ── plan.* event handling ──────────────────────────────────────
      // Creates/updates a chat message with planPanel metadata so that
      // Message.tsx renders PlanPhaseBar + PlanPhasePanel.
      if (msgType && msgType.startsWith('plan.')) {
        setLastMessage({ ...msg, event_type: msgType });

        const data = msg.data as Record<string, unknown> | undefined;
        const chatState = useChatStore.getState();
        const eventSessionId =
          ((data?.session_id as string) || (msg.session_id as string) || (msg.workflow_id as string) || '');
        const panelMsgId = getPlanPanelMessageId(eventSessionId);

        const PLAN_PHASE_IDS = ['context', 'research', 'planning', 'orchestrate', 'assembly'];
        const buildDefaultPlanPhases = () => {
          const phases: Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> = {};
          for (const pid of PLAN_PHASE_IDS) {
            phases[pid] = { status: 'pending' };
          }
          return phases;
        };

        const getExistingPlanMsg = () => {
          // Search across all sessions so resumed/reconnected plans in non-active
          // sessions are found. Switch active session if the message lives elsewhere
          // so that subsequent updateMessage calls target the correct session.
          const allMessages = chatState.sessions.flatMap((s) => s.messages);
          const found = findPlanMessageBySession(allMessages, eventSessionId);
          if (found) {
            const ownerSession = chatState.sessions.find((s) =>
              s.messages.some((m) => m.id === found.id),
            );
            if (ownerSession && ownerSession.id !== chatState.activeSessionId) {
              chatState.setActiveSession(ownerSession.id);
            }
          }
          return found;
        };

        // Merge artifact entries by key (accumulate, dedup)
        const mergeArtifacts = (
          existing: Array<{ key: string }>,
          incoming: Array<{ key: string }>,
        ) => {
          const byKey = new Map(existing.map(a => [a.key, a]));
          for (const a of incoming) byKey.set(a.key, a);
          return Array.from(byKey.values());
        };
        const getExistingArtifacts = (meta?: Record<string, unknown>) =>
          (meta?.planArtifacts as Array<{ key: string }>) || [];

        // plan.phase.prompt — show the input form for a phase
        if (msgType === 'plan.phase.prompt' && data) {
          const phase = (data.phase as string) || 'context';
          const sessionId = (data.session_id as string) || '';

          // Sync planStore.sessionId so document API calls use the
          // correct UUID (not a stale value from a previous browser session).
          if (sessionId) {
            usePlanStore.setState({ sessionId });
          }

          // Detect budget exhaustion from budget data so BudgetIndicator
          // can show the exhausted badge and resume form.
          const budgetInfo = data.budget as Record<string, unknown> | undefined;
          const budgetExhausted = !!budgetInfo
            && (budgetInfo.maxLlmCalls as number) > 0
            && (budgetInfo.remainingLlmCalls as number) <= 0;

          const existingMsg = getExistingPlanMsg();

          if (existingMsg) {
            const _rawPhases = existingMsg.metadata?.planPhases as Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> | undefined;
            const existingPhases = _rawPhases && Object.keys(_rawPhases).length > 0 ? { ..._rawPhases } : buildDefaultPlanPhases();
            const existingPlanPanel = existingMsg.metadata?.planPanel as Record<string, unknown> | undefined;
            // Mark previous in_progress phase as complete
            const prevPhase = existingMsg.metadata?.planCurrentPhase as string;
            if (prevPhase && existingPhases[prevPhase]?.status === 'in_progress') {
              existingPhases[prevPhase] = { ...existingPhases[prevPhase], status: 'complete' };
            }
            existingPhases[phase] = {
              ...existingPhases[phase],
              status: 'in_progress',
              data: { ...data, fields: data.fields || [], prefilled: data.prefilled || {} },
            };
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                message_type: 'plan_progress',
                planPanel: {
                  sessionId: sessionId || (existingPlanPanel?.sessionId as string) || '',
                  currentPhase: phase,
                  phases: existingPhases,
                  agentContent: undefined,
                  thinkingSteps: (existingMsg.metadata?.planPanel as Record<string, unknown>)?.thinkingSteps || [],
                  planContextItems: data.context_items || existingPlanPanel?.planContextItems || null,
                  planArtifacts: data.artifacts
                    ? mergeArtifacts(getExistingArtifacts(existingPlanPanel), data.artifacts as Array<{ key: string }>)
                    : getExistingArtifacts(existingPlanPanel) || undefined,
                  budget: data.budget || existingPlanPanel?.budget || undefined,
                  workflowStatus: budgetExhausted ? 'budget_exhausted' : (existingPlanPanel?.workflowStatus as string),
                  planTasks: (data.plan_tasks as Record<string, unknown>) || existingPlanPanel?.planTasks || undefined,
                },
                planCurrentPhase: phase,
                planPhases: existingPhases,
                timestamp: new Date(),
              },
            });
          } else {
            const phases = buildDefaultPlanPhases();
            phases[phase] = {
              status: 'in_progress',
              data: { ...data, fields: data.fields || [], prefilled: data.prefilled || {} },
            };
            chatState.addMessage({
              id: panelMsgId,
              role: 'assistant',
              type: 'text',
              content: '',
              metadata: {
                timestamp: new Date(),
                message_type: 'plan_progress',
                planPanel: {
                  sessionId,
                  currentPhase: phase,
                  phases,
                  agentContent: undefined,
                  thinkingSteps: [],
                  planContextItems: data.context_items || null,
                  planArtifacts: (data.artifacts as Array<{ key: string }>) || undefined,
                  workflowStatus: budgetExhausted ? 'budget_exhausted' : 'running',
                  planTasks: (data.plan_tasks as Record<string, unknown>) || undefined,
                },
                planCurrentPhase: phase,
                planPhases: phases,
              },
            });
          }

          // Stop the spinner on the plan_start message now that the plan is underway
          const activeSession = chatState.getActiveSession();
          const planStartMsg = activeSession?.messages.find(
            (m) => m.metadata?.message_type === 'plan_start'
          );
          if (planStartMsg) {
            chatState.updateMessage(planStartMsg.id, {
              metadata: {
                ...planStartMsg.metadata,
                timestamp: planStartMsg.metadata?.timestamp ?? new Date(),
                message_type: 'plan_active',
              },
            });
          }
        }

        // plan.phase.enter — a phase has started (agent processing, no form)
        if (msgType === 'plan.phase.enter' && data) {
          const phase = (data.phase as string);
          if (phase) {
            const existingMsg = getExistingPlanMsg();
            if (existingMsg?.metadata?.planPanel) {
              const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
              const _rawPhases = existingMsg.metadata?.planPhases as Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> | undefined;
              const existingPhases = _rawPhases && Object.keys(_rawPhases).length > 0 ? { ..._rawPhases } : buildDefaultPlanPhases();
              // Clear phase data (prompt/approval form) so the UI transitions
              // from the approval form to the progress/thinking-steps view.
              // This is critical for revision loops where the phase re-enters
              // after the user clicked "Request Revisions".
              // Preserve context_items from the old phase data so the context
              // panel survives phase re-entry.
              const oldPhaseData = existingPhases[phase]?.data as Record<string, unknown> | undefined;
              const preservedContextItems = oldPhaseData?.context_items;
              existingPhases[phase] = preservedContextItems
                ? { status: 'in_progress', data: { context_items: preservedContextItems } }
                : { status: 'in_progress' };
              const steps = [{ timestamp: Date.now(), phase, message: `Starting ${phase} phase` }];
              chatState.updateMessage(panelMsgId, {
                metadata: {
                  ...existingMsg.metadata,
                  planPanel: {
                    ...meta,
                    currentPhase: phase,
                    phases: existingPhases,
                    agentContent: undefined,
                    thinkingSteps: steps,
                    // Explicitly preserve context items and artifacts at panel level
                    planContextItems: meta.planContextItems ?? null,
                    planArtifacts: meta.planArtifacts ?? undefined,
                  },
                  planCurrentPhase: phase,
                  planPhases: existingPhases,
                  timestamp: new Date(),
                },
              });
            }
          }
        }

        // plan.phase.progress — update thinking steps / agent content
        if (msgType === 'plan.phase.progress' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const phase = (data.phase as string) || (meta.currentPhase as string);
            const step = { timestamp: Date.now(), phase, message: (data.message as string) || '' };
            const steps = [...((meta.thinkingSteps as Array<unknown>) || []), step];
            // Task-scoped events carry a task_id. Phase-level agentContent should only
            // be updated from phase-level events (no task_id), otherwise each completed
            // task overwrites the phase-level streaming content and leaks into BasePhaseContent.
            const progressTaskId = data.task_id as string | undefined;
            const incomingAgentContent = (data.agentContent as string) || (data.content as string);
            const updatedMeta: Record<string, unknown> = {
              ...meta,
              agentContent: progressTaskId ? meta.agentContent : (incomingAgentContent || meta.agentContent),
              thinkingSteps: steps,
            };
            if ((data.step as string) === 'task_research' && (data.agentContent as string)) {
              updatedMeta.researchSummary = (data.agentContent as string);
            }

            // Store agent_content per-task so it persists in TaskCard after subsequent events.
            if (progressTaskId && incomingAgentContent) {
              const planTasks = { ...((updatedMeta.planTasks as Record<string, unknown>) || {}) };
              const task = (planTasks[progressTaskId] as Record<string, unknown>) || {};
              if (task && Object.keys(task).length > 0) {
                planTasks[progressTaskId] = {
                  ...task,
                  agentContent: incomingAgentContent,
                  researchSummary: (data.step as string) === 'task_research'
                    ? incomingAgentContent
                    : (task.researchSummary as string | undefined),
                };
                updatedMeta.planTasks = planTasks;
              }
            }

            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: updatedMeta,
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.phase.complete — mark a phase as complete
        if (msgType === 'plan.phase.complete' && data) {
          const phase = (data.phase as string);
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel && phase) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const _rawPhases = existingMsg.metadata?.planPhases as Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> | undefined;
            const existingPhases = _rawPhases && Object.keys(_rawPhases).length > 0 ? { ..._rawPhases } : buildDefaultPlanPhases();
            existingPhases[phase] = { ...existingPhases[phase], status: 'complete', result: (data.result as Record<string, unknown>) || (data.result_summary ? { summary: data.result_summary as string } : undefined) };
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: { ...meta, phases: existingPhases, agentContent: undefined, thinkingSteps: meta.thinkingSteps || [] },
                planPhases: existingPhases,
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.tasks.dag — full DAG emitted at the start of orchestrate phase
        if (msgType === 'plan.tasks.dag' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const tasksList = (data.tasks as Array<Record<string, unknown>>) || [];
            const planTasks = { ...((meta.planTasks as Record<string, unknown>) || {}) };
            for (const t of tasksList) {
              const taskId = t.task_id as string;
              if (taskId && !planTasks[taskId]) {
                // Only initialize tasks that don't already exist — re-emitted DAGs
                // (e.g. after a budget increase resume) must not reset completed tasks.
                planTasks[taskId] = {
                  id: taskId,
                  name: (t.task_name as string) || 'Task',
                  status: 'pending',
                  priority: t.priority as string,
                  dependencies: (t.dependencies as string[]) || [],
                  events: [],
                  iterationCount: 0,
                };
              }
            }
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: { ...meta, planTasks },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.circuit_breaker — stopped early due to missing context
        if (msgType === 'plan.circuit_breaker' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: {
                  ...meta,
                  circuitBreaker: {
                    triggered: true,
                    message: data.message as string,
                  }
                },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.task.start — a task within a phase has started (e.g. orchestrate sub-tasks)
        if (msgType === 'plan.task.start' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const phase = (data.phase as string) || (meta.currentPhase as string) || 'orchestrate';
            const taskId = data.task_id as string;
            const taskName = (data.task_name as string) || (data.task as string) || 'Task';
            const stepMessage = `▶ Started: ${taskName}`;
            const step = { timestamp: Date.now(), phase, message: stepMessage };
            const steps = [...((meta.thinkingSteps as Array<unknown>) || []), step];
            const specSection = (data.spec_section as string) || null;
            const specSectionContent = (data.spec_section_content as string) || null;

            // Update planTasks
            const planTasks = { ...((meta.planTasks as Record<string, unknown>) || {}) };
            if (taskId) {
              const task = (planTasks[taskId] as Record<string, unknown>) || { id: taskId, name: taskName, events: [], iterationCount: 0 };
              planTasks[taskId] = {
                ...task,
                status: 'in_progress',
                events: [...(task.events as Array<unknown>), { timestamp: Date.now(), message: stepMessage }],
                specSection,
                specSectionContent,
              };
            }
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: { ...meta, thinkingSteps: steps, specSection, specSectionContent, planTasks },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.task.critique — critique feedback for a task
        if (msgType === 'plan.task.critique' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const phase = (data.phase as string) || (meta.currentPhase as string) || 'orchestrate';
            const taskId = data.task_id as string;
            const taskName = (data.task_name as string) || (data.task as string) || 'Task';
            const feedback = (data.feedback as string) || (data.message as string) || 'Reviewing...';
            const stepMessage = `✎ Critique [${taskName}]: ${feedback}`;
            const step = { timestamp: Date.now(), phase, message: stepMessage };
            const steps = [...((meta.thinkingSteps as Array<unknown>) || []), step];

            // Update planTasks
            const planTasks = { ...((meta.planTasks as Record<string, unknown>) || {}) };
            if (taskId) {
              const task = (planTasks[taskId] as Record<string, unknown>) || { id: taskId, name: taskName, events: [], iterationCount: 0 };
              const passed = data.passed as boolean | undefined;
              planTasks[taskId] = {
                ...task,
                status: passed ? 'complete' : 'critiquing',
                iterationCount: ((task.iterationCount as number) || 0) + 1,
                events: [...(task.events as Array<unknown>), { timestamp: Date.now(), message: stepMessage }],
              };
            }

            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: { ...meta, thinkingSteps: steps, planTasks },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.task.complete — a task within a phase has finished
        if (msgType === 'plan.task.complete' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const phase = (data.phase as string) || (meta.currentPhase as string) || 'orchestrate';
            const taskId = data.task_id as string;
            const taskName = (data.task_name as string) || (data.task as string) || 'Task';
            const specSection = (data.spec_section as string);
            const isApproved = data.approved !== false;
            const label = specSection ? `${taskName} — ${specSection}` : taskName;
            const icon = isApproved ? '✓ Completed:' : '⚠ Failed:';
            const suffix = isApproved ? '' : ' (Unapproved)';
            const stepMessage = `${icon} ${label}${suffix}`;
            const step = { timestamp: Date.now(), phase, message: stepMessage };
            const steps = [...((meta.thinkingSteps as Array<unknown>) || []), step];

            // Update planTasks
            const planTasks = { ...((meta.planTasks as Record<string, unknown>) || {}) };
            if (taskId) {
              const task = (planTasks[taskId] as Record<string, unknown>) || { id: taskId, name: taskName, events: [], iterationCount: 0 };
              planTasks[taskId] = {
                ...task,
                status: isApproved ? 'complete' : 'failed',
                events: [...(task.events as Array<unknown>), { timestamp: Date.now(), message: stepMessage }],
                specSection: (task.specSection as string | undefined) || specSection || (meta.specSection as string | undefined) || null,
                specSectionContent: (task.specSectionContent as string | undefined) || (meta.specSectionContent as string | undefined) || null,
                researchSummary: (task.researchSummary as string | undefined) || (meta.researchSummary as string | undefined) || null,
              };
            }

            // Step 19d: Clear transient task context on task complete
            const { specSection: _specSection, specSectionContent: _specContent, researchSummary: _researchSummary, ...restMeta } = meta as Record<string, unknown>;
            const clearedMeta = { ...restMeta, thinkingSteps: steps, planTasks } as Record<string, unknown>;
            const updatedArtifacts = data.artifacts
              ? mergeArtifacts(getExistingArtifacts(meta), data.artifacts as Array<{ key: string }>)
              : getExistingArtifacts(restMeta);
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: { ...clearedMeta, planArtifacts: updatedArtifacts || undefined },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.manifest.update — progressive document manifest updates during orchestration
        if (msgType === 'plan.manifest.update' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const entry = data.entry as Record<string, unknown>;
            const existingManifest = (meta.documentManifest as Record<string, unknown>) || {
              entries: [],
              totalDocuments: 0,
              totalTokens: 0,
            };
            const existingEntries = (existingManifest.entries as Array<Record<string, unknown>>) || [];
            // Upsert by taskId
            const taskId = entry?.taskId as string;
            const updatedEntries = existingEntries.filter(e => e.taskId !== taskId);
            if (entry) updatedEntries.push(entry);
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: {
                  ...meta,
                  documentManifest: {
                    ...existingManifest,
                    entries: updatedEntries,
                    totalDocuments: (data.total_documents as number) || updatedEntries.length,
                    totalTokens: (data.total_tokens as number) || 0,
                  },
                },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.complete — entire workflow done
        if (msgType === 'plan.complete' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const _rawPhases = existingMsg.metadata?.planPhases as Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> | undefined;
            const existingPhases = _rawPhases && Object.keys(_rawPhases).length > 0 ? { ..._rawPhases } : buildDefaultPlanPhases();
            for (const pid of Object.keys(existingPhases)) {
              if (existingPhases[pid].status !== 'complete') {
                existingPhases[pid] = { ...existingPhases[pid], status: 'complete' };
              }
            }
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                message_type: 'plan_complete',
                planPanel: {
                  ...meta,
                  phases: existingPhases,
                  documentManifest: (data.documentManifest || meta.documentManifest || null) as Record<string, unknown> | null,
                },
                planPhases: existingPhases,
                planDocuments: {
                  specDocumentUrl: (data.spec_document_url as string) || null,
                  storyCardsUrl: (data.story_cards_url as string) || null,
                },
                documentManifest: data.documentManifest || meta.documentManifest || null,
                timestamp: new Date(),
              },
            });
          } else {
            // No plan-panel exists yet (e.g. budget resume that completed
            // before any phase.prompt event). Create one with all phases
            // marked complete.
            const phases = buildDefaultPlanPhases();
            for (const pid of Object.keys(phases)) {
              phases[pid] = { ...phases[pid], status: 'complete' };
            }
            chatState.addMessage({
              id: panelMsgId,
              role: 'assistant',
              type: 'text',
              content: '',
              metadata: {
                timestamp: new Date(),
                message_type: 'plan_complete',
                planPanel: {
                  sessionId: (data.session_id as string) || '',
                  currentPhase: '',
                  phases,
                  agentContent: undefined,
                  thinkingSteps: [],
                },
                planCurrentPhase: '',
                planPhases: phases,
                planDocuments: {
                  specDocumentUrl: (data.spec_document_url as string) || null,
                  storyCardsUrl: (data.story_cards_url as string) || null,
                },
                documentManifest: data.documentManifest || null,
              },
            });
          }
        }

        // plan.error — mark workflow as errored
        if (msgType === 'plan.error' && data) {
          // SESSION_NOT_FOUND means the persisted sessionId is stale (e.g. backend
          // was restarted). Clear it silently so the user isn't shown a spurious
          // error card and future reconnects don't retry the dead session.
          if ((data.code as string) === 'SESSION_NOT_FOUND') {
            usePlanStore.getState().setSessionId(null);
            return;
          }
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const phase = (data.phase as string) || (meta.currentPhase as string);
            const _rawPhases = existingMsg.metadata?.planPhases as Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> | undefined;
            const existingPhases = _rawPhases && Object.keys(_rawPhases).length > 0 ? { ..._rawPhases } : buildDefaultPlanPhases();
            if (phase && existingPhases[phase]) {
              existingPhases[phase] = { ...existingPhases[phase], status: 'error' };
            }
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                message_type: 'plan_error',
                planPanel: { ...meta, phases: existingPhases },
                planPhases: existingPhases,
                timestamp: new Date(),
              },
            });
          } else {
            // No plan-panel exists yet. Create one with the errored phase.
            const phases = buildDefaultPlanPhases();
            const phase = (data.phase as string) || '';
            if (phase && phases[phase]) {
              phases[phase] = { ...phases[phase], status: 'error' };
            }
            chatState.addMessage({
              id: panelMsgId,
              role: 'assistant',
              type: 'text',
              content: '',
              metadata: {
                timestamp: new Date(),
                message_type: 'plan_error',
                planPanel: {
                  sessionId: (data.session_id as string) || '',
                  currentPhase: phase,
                  phases,
                  agentContent: undefined,
                  thinkingSteps: [],
                },
                planCurrentPhase: phase,
                planPhases: phases,
              },
            });
          }
        }

        // plan.cancelled — user-initiated cancel; clear session and update panel
        if (msgType === 'plan.cancelled' && data) {
          // Clear persisted sessionId so reconnect doesn't retry a cancelled session
          usePlanStore.getState().setSessionId(null);
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                message_type: 'plan_cancelled',
                planPanel: { ...meta },
                timestamp: new Date(),
              },
            });
          }
        }

        // plan.state — update phases so reconnect/resume restores UI
        if (msgType === 'plan.state' && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const meta = existingMsg.metadata.planPanel as Record<string, unknown>;
            const _rawPhases = existingMsg.metadata?.planPhases as Record<string, { status: string; data?: Record<string, unknown>; result?: Record<string, unknown> }> | undefined;
            const existingPhases = _rawPhases && Object.keys(_rawPhases).length > 0 ? { ..._rawPhases } : buildDefaultPlanPhases();
            const budgetData = data.budget as Record<string, unknown> | undefined;
            const hydratedState = hydratePlanStateSnapshot({
              existingPhases,
              data,
              phaseIds: PLAN_PHASE_IDS,
              fallbackContextItems: (meta.planContextItems as Record<string, unknown> | null | undefined) || null,
            });

            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: {
                  ...meta,
                  currentPhase: hydratedState.currentPhase || meta.currentPhase,
                  phases: hydratedState.phases,
                  planContextItems: hydratedState.contextItems,
                  planArtifacts: data.artifacts
                    ? mergeArtifacts(getExistingArtifacts(meta), data.artifacts as Array<{ key: string }>)
                    : getExistingArtifacts(meta) || undefined,
                  planTasks: (data.plan_tasks as Record<string, unknown>) || (meta.planTasks as Record<string, unknown> | undefined),
                  budget: budgetData || (meta.budget as Record<string, unknown> | undefined),
                  documentManifest: (data.document_manifest as Record<string, unknown>) || (meta.documentManifest as Record<string, unknown> | undefined),
                  specSection: ((data.task_context as Record<string, unknown> | undefined)?.spec_section as string | undefined) ?? (meta.specSection as string | undefined) ?? null,
                  specSectionContent: ((data.task_context as Record<string, unknown> | undefined)?.spec_section_content as string | undefined) ?? (meta.specSectionContent as string | undefined) ?? null,
                  researchSummary: ((data.task_context as Record<string, unknown> | undefined)?.research_summary as string | undefined) ?? (meta.researchSummary as string | undefined) ?? null,
                  workflowStatus: (data.workflow_status as string) || (meta.workflowStatus as string),
                },
                planCurrentPhase: hydratedState.currentPhase || existingMsg.metadata.planCurrentPhase,
                planPhases: hydratedState.phases,
                timestamp: new Date(),
              },
            });
          } else {
            // No plan-panel exists yet (resume/reconnect). Create one
            // with phase statuses from the state snapshot.
            const hydratedState = hydratePlanStateSnapshot({
              existingPhases: buildDefaultPlanPhases(),
              data,
              phaseIds: PLAN_PHASE_IDS,
            });
            const budgetData = data.budget as Record<string, unknown> | undefined;
            const artifacts = data.artifacts as Array<{ key: string }> | undefined;
            chatState.addMessage({
              id: panelMsgId,
              role: 'assistant',
              type: 'text',
              content: '',
              metadata: {
                timestamp: new Date(),
                message_type: 'plan_progress',
                planPanel: {
                  sessionId: (data.session_id as string) || '',
                  currentPhase: hydratedState.currentPhase,
                  phases: hydratedState.phases,
                  agentContent: undefined,
                  thinkingSteps: [],
                  planContextItems: hydratedState.contextItems,
                  planArtifacts: artifacts || undefined,
                  planTasks: (data.plan_tasks as Record<string, unknown>) || undefined,
                  budget: budgetData || undefined,
                  documentManifest: (data.document_manifest as Record<string, unknown>) || undefined,
                  specSection: ((data.task_context as Record<string, unknown> | undefined)?.spec_section as string | undefined) ?? null,
                  specSectionContent: ((data.task_context as Record<string, unknown> | undefined)?.spec_section_content as string | undefined) ?? null,
                  researchSummary: ((data.task_context as Record<string, unknown> | undefined)?.research_summary as string | undefined) ?? null,
                  workflowStatus: (data.workflow_status as string) || 'running',
                },
                planCurrentPhase: hydratedState.currentPhase,
                planPhases: hydratedState.phases,
              },
            });
          }
        }

        // plan.paused / plan.budget.warning — update store AND message metadata
        // so BudgetIndicator can show exhausted badge and resume form
        if ((msgType === 'plan.paused' || msgType === 'plan.budget.warning') && data) {
          const existingMsg = getExistingPlanMsg();
          if (existingMsg?.metadata?.planPanel) {
            const status =
              (data.status as string)
              || (msgType === 'plan.paused' ? 'paused' : 'running');
            chatState.updateMessage(panelMsgId, {
              metadata: {
                ...existingMsg.metadata,
                planPanel: {
                  ...(existingMsg.metadata.planPanel as Record<string, unknown>),
                  workflowStatus: status,
                },
                timestamp: new Date(),
              },
            });
          }
        }
      }
    });

    // -- Connection lifecycle -------------------------------------------------
    const unsubConnect = socket.on('connected', () => {
      console.log('[WebSocketContext] Connected event received');
      setIsConnected(true);
      setConnectionError(null);
      setReconnectAttempts(0);

      // Re-hydrate plan state after reconnect if a session was active.
      // Guard with _hasHydrated so we don't send stale sessionId before
      // the Zustand persist middleware has finished reading from localStorage.
      const planStore = usePlanStore.getState();
      if (planStore._hasHydrated && planStore.sessionId) {
        console.log('[WebSocketContext] Sending plan.reconnect for session', planStore.sessionId);
        socket.send({ type: 'plan.reconnect', payload: { session_id: planStore.sessionId } } as unknown as Parameters<typeof socket.send>[0]);
      }
    });
    
    const unsubDisconnect = socket.on('disconnected', (data: unknown) => {
      const disconnectData = data as { code?: number; reason?: string } | undefined;
      console.log('[WebSocketContext] Disconnected event received:', disconnectData);
      setIsConnected(false);
      setCurrentWorkflow((prev) => ({
        ...prev,
        status: 'idle',
      }));
      
      if (disconnectData?.code && disconnectData.code !== 1000) {
        setConnectionError(`Connection closed: ${disconnectData.reason || 'Unknown reason'}`);
      }
    });

    const unsubWsError = socket.on('ws_error', (error: unknown) => {
      console.error('[WebSocketContext] Error event received:', error);
      setConnectionError('WebSocket connection error');
    });

    const unsubMaxReconnect = socket.on('max_reconnect_attempts', (data: unknown) => {
      const attemptData = data as { attempts?: number } | undefined;
      console.error('[WebSocketContext] Max reconnection attempts reached:', attemptData?.attempts);
      setConnectionError(`Failed to reconnect after ${attemptData?.attempts || maxReconnectAttempts} attempts`);
      setReconnectAttempts(attemptData?.attempts || maxReconnectAttempts);
    });

    setWs(socket);
    socket.connect();
    // Sync connection state in case the socket was already open when this
    // component mounted (e.g., Next.js hot-reload remounts the provider
    // while the underlying singleton WebSocket stays connected).
    if (socket.isConnected) {
      setIsConnected(true);
    }

    return () => {
      // Only unsubscribe this component's handlers — don't kill the
      // shared socket.  This prevents dev-mode double-mount from
      // nuking the connection that the second mount just established.
      unsubProgress();
      unsubComplete();
      unsubError();
      unsubPreview();
      unsubPartial();
      unsubChatMessage();
      unsubGenericMessage();
      unsubConnect();
      unsubDisconnect();
      unsubWsError();
      unsubMaxReconnect();
    };
  }, [wsUrl, maxReconnectAttempts]);

  // ---------------------------------------------------------------------------
  // Generic send helper – works with both typed WSMessage and raw objects
  // ---------------------------------------------------------------------------
  const sendMessage = useCallback(
    (message: LegacyWSMessage | WSOutgoingMessage | Record<string, unknown>) => {
      if (!ws) return;

      // Route typed WSMessage start payloads through the class helpers
      if (
        'type' in message &&
        message.type === 'start' &&
        'payload' in message &&
        message.payload
      ) {
        const payload = message.payload as StartPayload;
        if (payload.workflow_type === 'ingest') {
          ws.startIngestWorkflow(payload.git_url || '', payload.branch || 'main');
          return;
        }
        if (payload.workflow_type === 'ask-code') {
          ws.startAskCodeWorkflow(payload.query || '', payload.repo_id || '');
          return;
        }
      }

      // For everything else, send the raw JSON via the public send helper
      ws.send(message);
    },
    [ws],
  );

  // ---------------------------------------------------------------------------
  // Typed helper: cancel a workflow (Req 8.7)
  // ---------------------------------------------------------------------------
  const sendCancel = useCallback(
    (workflowId: string) => {
      sendMessage({ type: 'cancel', workflow_id: workflowId });
    },
    [sendMessage],
  );

  // ---------------------------------------------------------------------------
  // Typed helper: reconnect to resume progress (Req 8.8, Req 30.7)
  // ---------------------------------------------------------------------------
  const sendReconnect = useCallback(
    (workflowId: string) => {
      sendMessage({ type: 'reconnect', workflow_id: workflowId });
    },
    [sendMessage],
  );

  // ---------------------------------------------------------------------------
  // Typed helper: pause / resume ingestion (Req 8.9, Req 30.4, Req 30.5)
  // ---------------------------------------------------------------------------
  const sendAction = useCallback(
    (action: 'pause' | 'resume') => {
      sendMessage({ type: 'action', action });
    },
    [sendMessage],
  );

  // ---------------------------------------------------------------------------
  // Typed helper: send user decision for workflow review (Req 20.1)
  // ---------------------------------------------------------------------------
  const sendInput = useCallback(
    (threadId: string, decision: V3WorkflowAction) => {
      sendMessage({
        type: 'input',
        payload: { thread_id: threadId, decision },
      });
    },
    [sendMessage],
  );

  // ---------------------------------------------------------------------------
  // Context value
  // ---------------------------------------------------------------------------
  const value: WebSocketContextValue = {
    ws,
    isConnected,
    connectionError,
    reconnectAttempts,
    maxReconnectAttempts,
    connect: () => ws?.connect(),
    disconnect: () => ws?.disconnect(),
    forceReconnect: () => {
      console.log('[WebSocketContext] Force reconnect requested');
      setConnectionError(null);
      setReconnectAttempts(0);
      ws?.forceReconnect();
    },
    sendMessage,
    currentWorkflow,
    setCurrentWorkflow,
    ingestionProgress,
    preview,
    lastMessage,
    sendCancel,
    sendReconnect,
    sendAction,
    sendInput,
  };

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}
