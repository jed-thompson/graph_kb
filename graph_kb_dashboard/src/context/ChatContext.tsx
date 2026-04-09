'use client';

import { createContext, useContext, useCallback, useState, useEffect, useRef, ReactNode, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ChatState, ChatMessage, ContextEntry, SpecPhaseProgressData } from '@/lib/types/chat';
import type { Repository, SourceItem } from '@/lib/types/api';
import { listRepositories } from '@/lib/api/repositories';
import { askCode, askCodeStream } from '@/lib/api/chat';
import { useWebSocket } from '@/context/WebSocketContext';
import type { AttachedFile } from '@/context/AttachmentContext';
import { useChatStore, useActiveSessionMessages, useChatStoreHydrated } from '@/lib/store/chatStore';
import type { ChatSessionMeta } from '@/lib/store/chatStore';
import { useResearchStore } from '@/lib/store/researchStore';

export const ChatContext = createContext<ChatState | null>(null);

export function useChat(): ChatState {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
}

/** Convert SourceItem[] from the API to the Source[] shape used in message metadata. */
function mapSources(items: SourceItem[]) {
  return items.map((s) => ({
    file_path: s.file_path,
    start_line: s.start_line,
    end_line: s.end_line,
    content: s.content,
    symbol: s.symbol,
    score: s.score,
  }));
}

export function ChatProvider({ children, getAttachmentFiles }: { children: ReactNode; getAttachmentFiles?: () => AttachedFile[] }) {
  const router = useRouter();
  const wsContext = useWebSocket();
  const sharedWs = wsContext?.ws ?? null;
  const wsConnected = wsContext?.isConnected ?? false;

  // Zustand store state and actions
  const sessions = useChatStore(state => state.sessions);
  const activeSessionId = useChatStore(state => state.activeSessionId);
  const createSession = useChatStore(state => state.createSession);
  const deleteSession = useChatStore(state => state.deleteSession);
  const setActiveSession = useChatStore(state => state.setActiveSession);
  const updateSessionTitle = useChatStore(state => state.updateSessionTitle);
  const addMessage = useChatStore(state => state.addMessage);
  const updateMessage = useChatStore(state => state.updateMessage);
  const clearMessages = useChatStore(state => state.clearMessages);
  const hasHydrated = useChatStoreHydrated();

  // Get deserialized messages from active session
  const messages = useActiveSessionMessages();

  // Local UI state
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentModel, setCurrentModel] = useState('claude-sonnet-4-20250219');
  const [contexts, setContexts] = useState<Map<string, ContextEntry[]>>(new Map());
  const [selectedContexts, setSelectedContexts] = useState<string[]>([]);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState<string | null>(null);

  // Multi-repo targeting from the research store
  const selectedRepoIds = useResearchStore((s) => s.selectedRepoIds);

  // Track active stream abort controller so we can cancel on unmount
  const streamControllerRef = useRef<AbortController | null>(null);

  // Debounce guard to prevent double-click creating duplicate plan sessions
  const planStartPending = useRef(false);

  // Track whether an ingest is in progress so we can subscribe/unsubscribe
  const [ingestActive, setIngestActive] = useState(false);

  // Track spec workflow blocking state (LLM phases block user input)
  const [isBlocked, setIsBlocked] = useState(false);
  const [specPhaseProgress, setSpecPhaseProgress] = useState<SpecPhaseProgressData | null>(null);

  // Plan name prompt dialog
  const [planNameDialogOpen, setPlanNameDialogOpen] = useState(false);

  // Initialize a session on mount if none exists.
  // Wait for hydration to complete before creating/activating sessions.
  useEffect(() => {
    // Don't do anything until hydration is complete
    if (!hasHydrated) return;

    if (!activeSessionId && sessions.length === 0) {
      createSession(selectedRepoId);
    } else if (!activeSessionId && sessions.length > 0) {
      const emptySession = sessions.find(s => s.title === 'New Chat' && s.messages.length === 0);
      setActiveSession(emptySession ? emptySession.id : sessions[0].id);
    }
  }, [hasHydrated, activeSessionId, sessions, createSession, setActiveSession, selectedRepoId]);

  // Session management functions
  const createNewChat = useCallback(() => {
    // Reuse an existing empty "New Chat" session if one exists
    const emptySession = sessions.find(s => s.title === 'New Chat' && s.messages.length === 0);
    if (emptySession) {
      setActiveSession(emptySession.id);
    } else {
      const newId = createSession(selectedRepoId);
      setActiveSession(newId);
    }
    setIsStreaming(false);
    setIsLoading(false);
  }, [sessions, createSession, setActiveSession, selectedRepoId]);

  const switchChat = useCallback((sessionId: string) => {
    setActiveSession(sessionId);
    setIsStreaming(false);
    setIsLoading(false);
  }, [setActiveSession]);

  const deleteChat = useCallback((sessionId: string) => {
    deleteSession(sessionId);
  }, [deleteSession]);

  const renameChat = useCallback((sessionId: string, title: string) => {
    updateSessionTitle(sessionId, title);
  }, [updateSessionTitle]);

  const clearChat = useCallback(() => {
    clearMessages();
    setInput('');
  }, [clearMessages]);

  // Derived sessions list for UI
  const sessionsList = useMemo<ChatSessionMeta[]>(() =>
    sessions.map(s => ({
      id: s.id,
      title: s.title,
      messageCount: s.messages.length,
      createdAt: s.createdAt,
      updatedAt: s.updatedAt,
    })),
    [sessions]
  );

  // Load repositories on mount
  useEffect(() => {
    async function loadRepos() {
      try {
        const response = await listRepositories({ limit: 50 });
        setRepositories(response.repos);
        const readyRepo = response.repos.find((r) => r.status === 'ready');
        if (readyRepo && !selectedRepoId) {
          setSelectedRepoId(readyRepo.id);
        }
      } catch (error) {
        console.error('Failed to load repositories:', error);
      }
    }
    loadRepos();

    return () => {
      streamControllerRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------------------
  // Subscribe to shared WebSocket progress/complete/error events while an
  // ingest is active so that updates appear as chat messages.
  // ---------------------------------------------------------------------------
  // Use a ref to hold the "progress message id" so the subscription callbacks
  // can update the same message without re-running the effect.
  const progressMsgIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!ingestActive || !sharedWs) return;

    // Create a single progress message that we'll keep updating in-place
    const progressId = `ingest-progress-${Date.now()}`;
    progressMsgIdRef.current = progressId;

    const progressMsg: ChatMessage = {
      id: progressId,
      role: 'system',
      type: 'text',
      content: 'Initializing...',
      metadata: { timestamp: new Date() },
    };
    addMessage(progressMsg);

    const unsubProgress = sharedWs.on('progress', (data: unknown) => {
      const event = data as Record<string, unknown>;
      // Backend wraps payload under event.data; fall back to top-level for compat
      const d = ((event.data ?? event) as Record<string, unknown>);
      const phase = (d.phase || d.step || 'initializing') as string;
      const pct = (d.progress_percent as number) ?? -1;
      const msg = (d.message as string) || '';
      const totalFiles = d.total_files as number | undefined;
      const processedFiles = d.processed_files as number | undefined;
      const totalChunks = d.total_chunks as number | undefined;
      const totalSymbols = d.total_symbols as number | undefined;

      // Build a concise status line
      let status = msg || `Phase: ${phase}`;
      if (totalFiles && totalFiles > 0) {
        status += ` | Files: ${processedFiles ?? 0}/${totalFiles}`;
      }
      if (totalChunks) {
        status += ` | Chunks: ${totalChunks}`;
      }
      if (totalSymbols) {
        status += ` | Symbols: ${totalSymbols}`;
      }
      if (pct > 0) {
        status += ` (${Math.round(pct)}%)`;
      }

      const id = progressMsgIdRef.current;
      if (!id) return;

      // Get current message to read existing steps (read directly from store to
      // avoid capturing `sessions` in the closure, which would make the effect
      // re-run every time a message is added and cause an infinite loop)
      const storeState = useChatStore.getState();
      const session = storeState.sessions.find(s => s.id === storeState.activeSessionId);
      const currentMsg = session?.messages.find(m => m.id === id);
      const existingSteps = (currentMsg?.metadata?.progress_steps as Array<{
        step: string;
        phase: string;
        message?: string;
        status: 'complete' | 'active' | 'pending';
      }>) || [];

      // Check if this phase already exists as a step
      const existingStepIndex = existingSteps.findIndex(s => s.step === phase);
      let updatedSteps: typeof existingSteps;

      if (existingStepIndex >= 0) {
        // Update existing step's message and keep status as active
        updatedSteps = existingSteps.map((s, idx) => ({
          ...s,
          status: idx <= existingStepIndex ? (idx === existingStepIndex ? 'active' as const : 'complete' as const) : s.status,
          ...(idx === existingStepIndex ? { message: status } : {}),
        }));
      } else {
        // New phase - mark all previous as complete and add new step
        updatedSteps = existingSteps.map((s) => ({ ...s, status: 'complete' as const }));
        updatedSteps.push({
          step: phase,
          phase: phase,
          message: status,
          status: 'active' as const,
        });
      }

      updateMessage(id, {
        metadata: {
          timestamp: new Date(),
          progress_steps: updatedSteps,
          progress_percent: pct,
          message_type: 'ingest_progress',
          ingest_stats: {
            totalFiles,
            processedFiles: processedFiles ?? (totalFiles ? 1 : 0),
            totalChunks,
            totalSymbols,
            progressPercent: pct,
          },
        },
      });
    });

    const unsubComplete = sharedWs.on('complete', (data: unknown) => {
      const event = data as Record<string, unknown>;
      const d = ((event.data ?? event) as Record<string, unknown>);
      const repoId = (d.repo_id as string) || '';
      const stats = d.stats as Record<string, number> | undefined;

      let summary = `✅ Repository **${repoId}** ingested successfully.`;
      if (stats) {
        summary += ` Files: ${stats.total_files}, Chunks: ${stats.total_chunks}, Symbols: ${stats.total_symbols}, Relationships: ${stats.total_relationships}`;
      }

      const id = progressMsgIdRef.current;
      if (id) {
        const storeState = useChatStore.getState();
        const session = storeState.sessions.find(s => s.id === storeState.activeSessionId);
        const currentMsg = session?.messages.find(m => m.id === id);
        const existingSteps = (currentMsg?.metadata?.progress_steps as Array<{
          step: string;
          phase: string;
          message?: string;
          status: 'complete' | 'active' | 'pending';
        }>) || [];
        const completedSteps = existingSteps.map((s) => ({ ...s, status: 'complete' as const }));
        completedSteps.push({
          step: 'complete',
          phase: 'Complete',
          message: summary,
          status: 'complete' as const,
        });

        updateMessage(id, {
          content: summary,
          metadata: {
            timestamp: new Date(),
            progress_steps: completedSteps,
            message_type: 'ingest_complete',
          },
        });
      }
      setIngestActive(false);
      setIsLoading(false);

      // Refresh the repo list so the new repo appears in the selector
      listRepositories({ limit: 50 })
        .then((res) => setRepositories(res.repos))
        .catch(() => { });
    });

    const unsubError = sharedWs.on('error', (data: unknown) => {
      const event = data as Record<string, unknown>;
      const d = ((event.data ?? event) as Record<string, unknown>);
      const errMsg = (d.message as string) || 'Unknown error during ingestion';

      const id = progressMsgIdRef.current;
      if (id) {
        updateMessage(id, { content: `❌ Ingest failed: ${errMsg}`, type: 'error' });
      }
      setIngestActive(false);
      setIsLoading(false);
    });

    return () => {
      unsubProgress();
      unsubComplete();
      unsubError();
      progressMsgIdRef.current = null;
    };
  }, [ingestActive, sharedWs, addMessage, updateMessage]);

  // ---------------------------------------------------------------------------
  // Subscribe to spec.phase.progress events to block UI during LLM phases
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!sharedWs) return;

    const unsubProgress = sharedWs.on('spec.phase.progress', (data: unknown) => {
      const d = data as SpecPhaseProgressData;
      setSpecPhaseProgress(d);
      setIsBlocked(true);
    });

    const unsubComplete = sharedWs.on('spec.phase.complete', () => {
      setIsBlocked(false);
    });

    const unsubError = sharedWs.on('spec.error', () => {
      setIsBlocked(false);
    });

    const unsubSpecComplete = sharedWs.on('spec.complete', () => {
      setIsBlocked(false);
      setSpecPhaseProgress(null);
    });

    return () => {
      unsubProgress();
      unsubComplete();
      unsubError();
      unsubSpecComplete();
    };
  }, [sharedWs]);

  // ---------------------------------------------------------------------------
  // Subscribe to plan.phase.* events to block UI during plan workflow
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!sharedWs) return;

    const unsubPlanProgress = sharedWs.on('plan.phase.progress', () => {
      setIsBlocked(true);
    });

    const unsubPlanComplete = sharedWs.on('plan.phase.complete', () => {
      setIsBlocked(false);
    });

    const unsubPlanError = sharedWs.on('plan.error', () => {
      setIsBlocked(false);
    });

    const unsubPlanFullComplete = sharedWs.on('plan.complete', () => {
      setIsBlocked(false);
    });

    const unsubPlanPrompt = sharedWs.on('plan.phase.prompt', () => {
      setIsBlocked(false);
    });

    return () => {
      unsubPlanProgress();
      unsubPlanComplete();
      unsubPlanError();
      unsubPlanFullComplete();
      unsubPlanPrompt();
    };
  }, [sharedWs]);

  // ---------------------------------------------------------------------------
  // Plan flow helper: sends plan.start over WebSocket
  // ---------------------------------------------------------------------------
  const startPlanFlow = useCallback(
    (planName: string): boolean => {
      if (planStartPending.current) return false;

      if (!sharedWs || !wsConnected) {
        const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';
        const errorMessage: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'system',
          type: 'error',
          content: `WebSocket not connected. Backend at ${wsUrl} may not be responding.`,
          metadata: { timestamp: new Date() },
        };
        addMessage(errorMessage);
        return false;
      }

      planStartPending.current = true;
      setTimeout(() => { planStartPending.current = false; }, 2000);

      const startMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        type: 'plan',
        content: `Starting Plan Workflow: ${planName}...`,
        metadata: { timestamp: new Date(), message_type: 'plan_start' },
      };
      addMessage(startMessage);

      sharedWs.send({
        type: 'plan.start',
        payload: {
          name: planName,
          description: planName,
        },
      });

      return true;
    },
    [sharedWs, wsConnected, addMessage],
  );

  // Public callbacks for the plan name dialog
  const startPlanWithName = useCallback(
    (name: string) => {
      setPlanNameDialogOpen(false);
      startPlanFlow(name.trim());
    },
    [startPlanFlow],
  );

  const cancelPlanNameDialog = useCallback(() => {
    setPlanNameDialogOpen(false);
  }, []);

  // ---------------------------------------------------------------------------
  // Helper: handle slash commands that don't go through the LLM
  // Returns true if the input was handled as a command.
  // ---------------------------------------------------------------------------
  const handleCommand = useCallback(
    (trimmedInput: string): boolean => {
      if (!trimmedInput.startsWith('/')) return false;

      const parts = trimmedInput.split(' ');
      const command = parts[0].slice(1);

      if (command === 'ingest' && parts.length > 1) {
        const gitUrl = parts[1];
        const branch = parts[2] || 'main';

        if (!sharedWs || !wsConnected) {
          const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';
          const errorMessage: ChatMessage = {
            id: (Date.now() + 1).toString(),
            role: 'system',
            type: 'error',
            content: `WebSocket not connected. Backend at ${wsUrl} may not be responding.`,
            metadata: { timestamp: new Date() },
          };
          addMessage(errorMessage);
          return true;
        }

        const ingestMessage: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'system',
          type: 'text',
          content: `Starting ingest for ${gitUrl} (branch: ${branch})...`,
          metadata: { timestamp: new Date() },
        };
        addMessage(ingestMessage);
        setIsLoading(true);

        // Activate the subscription effect that listens for progress events
        setIngestActive(true);

        // Send the start message through the shared singleton
        sharedWs.startIngestWorkflow(gitUrl, branch);

        return true;
      }

      if (command === 'clear') {
        clearChat();
        setIsStreaming(false);
        setIsLoading(false);
        return true;
      }

      if (command === 'wizard') {
        // Redirect to /spec command for new conversational wizard
        const wizardMessage: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'system',
          type: 'text',
          content: '🧙 The wizard has moved to /spec. Type /spec to start the Feature Spec Wizard.',
          metadata: { timestamp: new Date() },
        };
        addMessage(wizardMessage);
        return true;
      }

      if (command === 'plan') {
        const planName = parts.slice(1).join(' ').trim();

        if (!planName) {
          // No name provided — prompt the user
          setPlanNameDialogOpen(true);
          return true;
        }

        return startPlanFlow(planName);
      }

      return false;
    },
    [clearChat, sharedWs, wsConnected, addMessage, router, startPlanFlow, setPlanNameDialogOpen],
  );

  // ---------------------------------------------------------------------------
  // Auto-resume plan session from /plan page redirect
  // ---------------------------------------------------------------------------
  const planResumeHandled = useRef(false);
  useEffect(() => {
    if (planResumeHandled.current) return;
    if (!hasHydrated || !wsConnected || !sharedWs) return;

    const resumeSessionId = localStorage.getItem('graphkb-plan-resume');
    if (!resumeSessionId) return;

    planResumeHandled.current = true;
    localStorage.removeItem('graphkb-plan-resume');

    sharedWs.send({
      type: 'plan.resume',
      payload: { session_id: resumeSessionId },
    });

    const resumeMessage: ChatMessage = {
      id: `plan-resume-${Date.now()}`,
      role: 'system',
      type: 'text',
      content: '📋 Resuming plan session...',
      metadata: { timestamp: new Date() },
    };
    addMessage(resumeMessage);
  }, [hasHydrated, wsConnected, sharedWs, addMessage]);

  // ---------------------------------------------------------------------------
  // sendMessage — calls /api/v1/chat/ask (non-streaming)
  // ---------------------------------------------------------------------------
  const sendMessage = useCallback(async () => {
    if (!input.trim()) return;

    const trimmedInput = input.trim();
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: trimmedInput,
      type: 'text',
      metadata: { timestamp: new Date() },
    };

    addMessage(userMessage);
    setInput('');
    setIsLoading(true);

    try {
      if (handleCommand(trimmedInput)) {
        return;
      }

      if (!selectedRepoId) {
        // No repo selected — still send to backend for general QA
      }

      const contextFiles = getAttachmentFiles?.().map((f) => ({
        name: f.name,
        content: f.content,
        mimeType: f.mimeType,
      }));

      const response = await askCode({
        ...(selectedRepoId ? { repo_id: selectedRepoId } : {}),
        query: trimmedInput,
        ...(contextFiles && contextFiles.length > 0 ? { context_files: contextFiles } : {}),
      });

      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.answer,
        type: 'text',
        metadata: {
          timestamp: new Date(),
          model: response.model || currentModel,
          sources: mapSources(response.sources),
          total_sources: response.sources.length,
          workflow_id: response.workflow_id,
          mermaid_diagrams: response.mermaid_diagrams,
          intent: response.intent ?? undefined,
        },
      };

      addMessage(assistantMessage);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'system',
        type: 'error',
        content: `Error: ${error instanceof Error ? error.message : 'Failed to send message'}`,
        metadata: { timestamp: new Date() },
      };
      addMessage(errorMessage);
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, selectedRepoId, currentModel, handleCommand, addMessage]);

  // ---------------------------------------------------------------------------
  // streamMessage — calls /api/v1/chat/ask/stream (SSE streaming)
  // ---------------------------------------------------------------------------
  const streamMessage = useCallback(async () => {
    if (!input.trim()) return;

    const trimmedInput = input.trim();
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: trimmedInput,
      type: 'text',
      metadata: { timestamp: new Date() },
    };

    addMessage(userMessage);
    setInput('');

    if (handleCommand(trimmedInput)) {
      return;
    }

    const assistantId = (Date.now() + 1).toString();

    // Insert a placeholder assistant message that will be updated as chunks arrive
    const placeholderMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      type: 'text',
      metadata: {
        timestamp: new Date(),
        model: currentModel,
        isStreaming: true,
      },
    };

    addMessage(placeholderMessage);
    setIsStreaming(true);
    setIsLoading(true);

    const streamContextFiles = getAttachmentFiles?.().map((f) => ({
      name: f.name,
      content: f.content,
      mimeType: f.mimeType,
    }));

    // When 2+ repos are selected in the research panel, use multi-repo mode
    const multiRepo = selectedRepoIds.length >= 2;
    const controller = askCodeStream(
      {
        ...(multiRepo
          ? { repo_ids: selectedRepoIds }
          : selectedRepoId
          ? { repo_id: selectedRepoId }
          : {}),
        query: trimmedInput,
        conversation_id: activeSessionId ?? undefined,
        ...(streamContextFiles && streamContextFiles.length > 0 ? { context_files: streamContextFiles } : {}),
      },
      {
        onChunk: (chunk) => {
          // Get current content from store
          const session = useChatStore.getState().sessions.find(s => s.id === useChatStore.getState().activeSessionId);
          const msg = session?.messages.find(m => m.id === assistantId);
          const currentContent = msg?.content || '';
          updateMessage(assistantId, { content: currentContent + chunk });
        },
        onSources: (sources, metadata) => {
          const session = useChatStore.getState().sessions.find(s => s.id === useChatStore.getState().activeSessionId);
          const msg = session?.messages.find(m => m.id === assistantId);
          updateMessage(assistantId, {
            metadata: {
              ...msg?.metadata,
              timestamp: new Date(),
              sources: mapSources(sources),
              total_sources: metadata?.total_sources,
              workflow_id: metadata?.workflow_id,
            },
          });
        },
        onMermaidDiagrams: (diagrams) => {
          const session = useChatStore.getState().sessions.find(s => s.id === useChatStore.getState().activeSessionId);
          const msg = session?.messages.find(m => m.id === assistantId);
          updateMessage(assistantId, {
            metadata: {
              ...msg?.metadata,
              timestamp: new Date(),
              mermaid_diagrams: diagrams,
            },
          });
        },
        onProgress: (progress) => {
          const session = useChatStore.getState().sessions.find(s => s.id === useChatStore.getState().activeSessionId);
          const msg = session?.messages.find(m => m.id === assistantId);
          const existingSteps = (msg?.metadata?.progress_steps as Array<{
            step: string;
            phase: string;
            message?: string;
            status: 'complete' | 'active' | 'pending';
          }>) || [];

          // Find if this step already exists
          const stepIndex = existingSteps.findIndex(s => s.step === progress.step);

          let updatedSteps: typeof existingSteps;
          if (stepIndex >= 0) {
            // Update existing step - mark as complete if we're past it
            updatedSteps = existingSteps.map((s, idx) => {
              if (idx === stepIndex) {
                return { ...s, status: 'active' as const, message: progress.message };
              }
              if (idx < stepIndex) {
                return { ...s, status: 'complete' as const };
              }
              return s;
            });
          } else {
            // Add new step - mark previous steps as complete
            updatedSteps = existingSteps.map(s => ({ ...s, status: 'complete' as const }));
            updatedSteps.push({
              step: progress.step ?? '',
              phase: progress.phase ?? '',
              message: progress.message,
              status: 'active' as const,
            });
          }

          updateMessage(assistantId, {
            metadata: {
              ...msg?.metadata,
              timestamp: new Date(),
              progress_steps: updatedSteps,
              progress_percent: progress.progress_percent,
              current_step: progress.current_step,
              total_steps: progress.total_steps,
            },
          });
        },
        onDone: (response) => {
          const session = useChatStore.getState().sessions.find(s => s.id === useChatStore.getState().activeSessionId);
          const msg = session?.messages.find(m => m.id === assistantId);

          // Mark all progress steps as complete
          const progressSteps = (msg?.metadata?.progress_steps as Array<{
            step: string;
            phase: string;
            message?: string;
            status: 'complete' | 'active' | 'pending';
          }>) || [];
          const completedSteps = progressSteps.map(s => ({ ...s, status: 'complete' as const }));

          updateMessage(assistantId, {
            // Keep accumulated content from streaming, use response.answer as fallback
            content: msg?.content || response.answer,
            metadata: {
              ...msg?.metadata,
              timestamp: new Date(),
              model: response.model || currentModel,
              sources: mapSources(response.sources),
              mermaid_diagrams: response.mermaid_diagrams,
              intent: response.intent ?? undefined,
              progress_steps: completedSteps,
              isStreaming: false,
            },
          });
          setIsStreaming(false);
          setIsLoading(false);
        },
        onError: (error) => {
          console.error('Stream error:', error);
          const session = useChatStore.getState().sessions.find(s => s.id === useChatStore.getState().activeSessionId);
          const msg = session?.messages.find(m => m.id === assistantId);
          updateMessage(assistantId, {
            content: msg?.content || `Error: ${error.message}`,
            type: msg?.content ? 'text' : 'error',
            metadata: {
              ...msg?.metadata,
              timestamp: new Date(),
              isStreaming: false,
            },
          });
          setIsStreaming(false);
          setIsLoading(false);
        },
      },
    );

    streamControllerRef.current = controller;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, selectedRepoId, selectedRepoIds, currentModel, handleCommand, addMessage, updateMessage]);

  // ---------------------------------------------------------------------------
  // Context helpers (unchanged)
  // ---------------------------------------------------------------------------
  const selectModel = useCallback((model: string) => {
    setCurrentModel(model);
  }, []);

  const addContext = useCallback((context: ContextEntry) => {
    const convId = Date.now().toString();
    setContexts((prev) => {
      const newMap = new Map(prev);
      if (!newMap.has(convId)) {
        newMap.set(convId, []);
      }
      const entries = newMap.get(convId) || [];
      entries.push(context);
      newMap.set(convId, entries);
      return newMap;
    });
  }, []);

  const removeContext = useCallback((id: string) => {
    setContexts((prev) => {
      const newMap = new Map(prev);
      for (const [convId, entries] of newMap.entries()) {
        const filtered = entries.filter((entry) => entry.id !== id);
        newMap.set(convId, filtered);
      }
      return newMap;
    });
  }, []);

  const toggleContext = useCallback((id: string) => {
    setSelectedContexts((prev) => {
      if (prev.includes(id)) {
        return prev.filter((ctxId) => ctxId !== id);
      }
      return [...prev, id];
    });
  }, []);

  const executeCommand = useCallback(async (command: string) => {
    console.log('Executing command:', command);
  }, []);

  // ---------------------------------------------------------------------------
  // Provider value
  // ---------------------------------------------------------------------------
  const sendWorkflowInput = useCallback((workflowId: string, payload: Record<string, unknown>) => {
    // Send clarification response via WebSocket
    if (sharedWs && wsConnected) {
      wsContext?.sendMessage({
        type: 'input',
        payload: {
          thread_id: workflowId,
          clarification_responses: payload,
        },
      });
    }
  }, [sharedWs, wsConnected, wsContext]);

  const value: ChatState = {
    messages,
    input,
    setInput,
    sendMessage,
    streamMessage,
    clearChat,
    isStreaming,
    isLoading,
    isBlocked,
    specPhaseProgress,
    currentModel,
    selectModel,
    contexts,
    selectedContexts,
    addContext,
    removeContext,
    toggleContext,
    executeCommand,
    sendWorkflowInput,
    repositories,
    selectedRepoId,
    setSelectedRepoId,
    // Session management
    createNewChat,
    switchChat,
    deleteChat,
    renameChat,
    activeSessionId,
    sessions: sessionsList,
    // Plan name prompt
    planNameDialogOpen,
    startPlanWithName,
    cancelPlanNameDialog,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
