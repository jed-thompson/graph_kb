'use client';

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MarkdownRenderer, MermaidDiagram } from '@/components/chat/MarkdownRenderer';
import { ProgressSteps, parseProgressSteps, stripProgressSteps } from '@/components/chat/ProgressSteps';
import { PlanPhasePanel } from '@/components/plan/PlanPhasePanel';
import { PlanPhaseBar } from '@/components/plan/PlanPhaseBar';
import { BudgetIndicator } from '@/components/plan/BudgetIndicator';
import { usePlanStore } from '@/lib/store/planStore';
import { PLAN_PHASES } from '@/lib/store/planStore';
import { CascadeWarningBanner } from '@/components/plan/CascadeWarningBanner';
import { PlanDocumentDownload } from '@/components/plan/PlanDocumentDownload';
import type { PlanPanelMetadata } from '@/components/plan/PlanContext';
import type { PlanPhaseId } from '@/lib/store/planStore';
import { FileCode, MapPin, ExternalLink, Bot, Loader2, CheckCircle, XCircle, Zap, Brain, GitBranch, Users, ClipboardList, Download, BookmarkPlus } from 'lucide-react';
import { apiClient } from '@/lib/api/client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import type { ChatMessage, Source } from '@/lib/types/chat';
import { getWebSocket } from '@/lib/api/websocket';

interface MessageProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

/**
 * Renders a single source reference badge showing file path and optional line range.
 */
function SourceBadge({ source, index }: { source: Source; index: number }) {
  const fileName = source.file_path.split('/').pop() || source.file_path;
  const hasLines = source.start_line != null;
  const lineRange =
    hasLines && source.end_line != null && source.end_line !== source.start_line
      ? `L${source.start_line}–${source.end_line}`
      : hasLines
        ? `L${source.start_line}`
        : null;

  return (
    <span
      key={index}
      className="inline-flex items-center gap-1 text-xs bg-muted/80 text-muted-foreground border border-border rounded-md px-2 py-1 hover:bg-muted transition-colors"
      title={`${source.file_path}${lineRange ? ` (${lineRange})` : ''}`}
    >
      <FileCode className="h-3 w-3 flex-shrink-0 text-primary" />
      <span className="font-mono truncate max-w-[180px]">{fileName}</span>
      {lineRange && (
        <>
          <MapPin className="h-3 w-3 flex-shrink-0 text-muted-foreground/70" />
          <span className="text-muted-foreground/80 font-mono">{lineRange}</span>
        </>
      )}
    </span>
  );
}

/**
 * Intent configuration with icons and styling.
 */
const INTENT_CONFIG: Record<string, {
  icon: React.ElementType;
  label: string;
  bgColor: string;
  textColor: string;
  borderColor: string;
}> = {
  ask_code: {
    icon: Zap,
    label: 'Quick Query',
    bgColor: 'bg-amber-100 dark:bg-amber-500/20',
    textColor: 'text-amber-700 dark:text-amber-400',
    borderColor: 'border-amber-300 dark:border-amber-500/30',
  },
  deep_analysis: {
    icon: Brain,
    label: 'Deep Analysis',
    bgColor: 'bg-purple-100 dark:bg-purple-500/20',
    textColor: 'text-purple-700 dark:text-purple-400',
    borderColor: 'border-purple-300 dark:border-purple-500/30',
  },
  ingest_repo: {
    icon: GitBranch,
    label: 'Repository Ingest',
    bgColor: 'bg-emerald-100 dark:bg-emerald-500/20',
    textColor: 'text-emerald-700 dark:text-emerald-400',
    borderColor: 'border-emerald-300 dark:border-emerald-500/30',
  },
  multi_agent: {
    icon: Users,
    label: 'Multi-Agent',
    bgColor: 'bg-cyan-100 dark:bg-cyan-500/20',
    textColor: 'text-cyan-700 dark:text-cyan-400',
    borderColor: 'border-cyan-300 dark:border-cyan-500/30',
  },
};

/**
 * Renders an intent badge showing the detected query type.
 */
function IntentBadge({ intent }: { intent: string }) {
  const config = INTENT_CONFIG[intent];
  if (!config) return null;

  const Icon = config.icon;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 border',
        config.bgColor,
        config.textColor,
        config.borderColor
      )}
      title={`Query classified as: ${intent}`}
    >
      <Icon className="h-3.5 w-3.5" />
      <span>{config.label}</span>
    </span>
  );
}

/**
 * Typing indicator shown while streaming assistant responses.
 */
function TypingIndicator() {
  return (
    <span className="inline-flex items-center gap-1 ml-1">
      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce [animation-delay:0ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce [animation-delay:150ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce [animation-delay:300ms]" />
    </span>
  );
}

interface AssistantMessageBodyProps {
  message: import('@/lib/types/chat').ChatMessage;
  displayContent: string;
  hasDisplayContent: boolean;
  isCurrentlyStreaming: boolean | undefined;
  progressSteps: import('@/components/chat/ProgressSteps').ProgressStep[] | null;
  mermaidDiagrams: string[];
  intent: string | undefined;
}

type SaveStatus = 'idle' | 'prompting' | 'saving' | 'saved' | 'error';

/**
 * Renders the assistant message body with optional save/download action buttons.
 */
function AssistantMessageBody({
  message,
  displayContent,
  hasDisplayContent,
  isCurrentlyStreaming,
  progressSteps,
  mermaidDiagrams,
  intent,
}: AssistantMessageBodyProps) {
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveName, setSaveName] = useState('');
  const [saveCategory, setSaveCategory] = useState('chat_responses');

  const defaultName = `response-${message.id.slice(0, 8)}`;

  const handleDownload = useCallback(() => {
    const blob = new Blob([displayContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${defaultName}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [displayContent, defaultName]);

  const handleSaveClick = useCallback(() => {
    setSaveName(defaultName);
    setSaveStatus('prompting');
  }, [defaultName]);

  const handleSaveConfirm = useCallback(async () => {
    setSaveStatus('saving');
    try {
      const blob = new Blob([displayContent], { type: 'text/markdown' });
      const filename = (saveName.trim() || defaultName).replace(/\.md$/, '') + '.md';
      const form = new FormData();
      form.append('file', blob, filename);
      if (saveCategory.trim()) form.append('category', saveCategory.trim());
      form.append('force', 'true');
      await apiClient.postForm('/docs/upload', form);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 3000);
    }
  }, [displayContent, saveName, saveCategory, defaultName]);

  const handleSaveCancel = useCallback(() => {
    setSaveStatus('idle');
  }, []);

  const showActions = hasDisplayContent && !isCurrentlyStreaming;

  return (
    <div className="space-y-4">
      {isCurrentlyStreaming && !hasDisplayContent && !progressSteps && <LoadingSkeleton />}

      {progressSteps && progressSteps.length > 0 && (
        <ProgressSteps
          steps={progressSteps}
          title="Code Analysis"
          variant="default"
          defaultCollapsed={false}
          intent={intent}
        />
      )}

      {hasDisplayContent && (
        <MarkdownRenderer
          content={displayContent}
          enableMermaid={true}
          enableCodeHighlight={true}
        />
      )}

      {isCurrentlyStreaming && hasDisplayContent && <TypingIndicator />}

      {mermaidDiagrams.length > 0 && mermaidDiagrams.map((diagram, idx) => (
        <MermaidDiagram key={`meta-mermaid-${idx}`} chart={diagram} />
      ))}

      {showActions && saveStatus === 'prompting' && (
        <div className="flex flex-col gap-2 pt-1 p-3 rounded-lg border border-border bg-muted/40">
          <div className="flex gap-2">
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">Filename</label>
              <input
                className="w-full text-xs rounded border border-input bg-background px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder={defaultName}
              />
            </div>
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">Category</label>
              <input
                className="w-full text-xs rounded border border-input bg-background px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring"
                value={saveCategory}
                onChange={(e) => setSaveCategory(e.target.value)}
                placeholder="chat_responses"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleSaveConfirm}
              className="inline-flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1 rounded hover:bg-primary/90 transition-colors"
            >
              <BookmarkPlus className="h-3.5 w-3.5" />
              Save
            </button>
            <button
              onClick={handleSaveCancel}
              className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded hover:bg-muted transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {showActions && saveStatus !== 'prompting' && (
        <div className="flex items-center gap-1 pt-1">
          <button
            onClick={handleDownload}
            title="Download as .md file"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-muted"
          >
            <Download className="h-3.5 w-3.5" />
            Download
          </button>
          <button
            onClick={handleSaveClick}
            disabled={saveStatus === 'saving' || saveStatus === 'saved'}
            title="Save to documents"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saveStatus === 'saving' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {saveStatus === 'saved' && <CheckCircle className="h-3.5 w-3.5 text-green-500" />}
            {saveStatus === 'error' && <XCircle className="h-3.5 w-3.5 text-red-500" />}
            {(saveStatus === 'idle') && <BookmarkPlus className="h-3.5 w-3.5" />}
            {saveStatus === 'saving' ? 'Saving…' : saveStatus === 'saved' ? 'Saved' : saveStatus === 'error' ? 'Failed' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Loading skeleton shown while waiting for the initial LLM response.
 */
function LoadingSkeleton() {
  return (
    <div className="space-y-2 animate-pulse">
      <div className="h-3 bg-muted rounded w-3/4" />
      <div className="h-3 bg-muted rounded w-1/2" />
      <div className="h-3 bg-muted rounded w-5/6" />
    </div>
  );
}

export const Message = memo(function Message({ message, isStreaming }: MessageProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const isAssistant = message.role === 'assistant';
  const sources = useMemo(() => (message.metadata?.sources as Source[] | undefined) || [], [message.metadata?.sources]);
  const totalSources = (message.metadata?.total_sources as number | undefined) || sources.length;
  const workflowId = message.metadata?.workflow_id as string | undefined;

  const cascadeWarning = usePlanStore(state => state.cascadeWarning);
  const setCascadeWarning = usePlanStore(state => state.setCascadeWarning);
  const [pendingNavigatePhase, setPendingNavigatePhase] = useState<string | null>(null);
  const [viewingPhase, setViewingPhase] = useState<PlanPhaseId | null>(null);
  const router = useRouter();

  // Extract plan currentPhase at component top level for hook dependencies
  const planPanelMeta = message.metadata?.planPanel as Record<string, unknown> | undefined;
  const backendCurrentPhase = (planPanelMeta?.currentPhase as PlanPhaseId) || null;

  // Auto-clear viewingPhase when backend advances to a new phase
  useEffect(() => {
    setViewingPhase(null);
  }, [backendCurrentPhase]);

  // Local view-only navigation (no backend interaction)
  const handlePhaseView = useCallback((targetPhase: PlanPhaseId) => {
    // Clicking the active phase clears the viewing override
    setViewingPhase(prev => prev === targetPhase ? null : targetPhase);
  }, []);

  // Deduplicate sources by file path - show unique files only
  const uniqueFileSources = useMemo(() => {
    const seenPaths = new Set<string>();
    const unique: Source[] = [];
    for (const source of sources) {
      if (!seenPaths.has(source.file_path)) {
        seenPaths.add(source.file_path);
        unique.push(source);
      }
    }
    return unique.slice(0, 20);
  }, [sources]);

  const uniqueFileCount = useMemo(() => {
    const paths = new Set(sources.map(s => s.file_path));
    return paths.size;
  }, [sources]);
  const hasMoreSources = totalSources > sources.length && workflowId;
  const hasSources = sources.length > 0;
  const mermaidDiagrams = (message.metadata?.mermaid_diagrams as string[] | undefined) || [];
  const isCurrentlyStreaming = isStreaming && isAssistant;
  const hasContent = message.content.length > 0;
  const intent = message.metadata?.intent as string | undefined;

  // Message type detection
  const messageType = message.metadata?.message_type as string | undefined;

  // Plan workflow message type detection
  const isPlanWorkflow = messageType?.startsWith('plan_') || !!message.metadata?.planPanel;
  const isPlanStart = messageType === 'plan_start';
  const isPlanProgress = messageType === 'plan_progress';
  const isPlanComplete = messageType === 'plan_complete';
  const isPlanError = messageType === 'plan_error';

  // Ingest message type detection
  const isIngest = messageType?.startsWith('ingest') || false;
  const isIngestProgress = messageType === 'ingest_progress';
  const isIngestComplete = messageType === 'ingest_complete';
  const isIngestError = messageType === 'ingest_error';
  const ingestProgressSteps = (message.metadata?.progress_steps as Array<{
    step: string;
    phase: string;
    message: string;
    status: 'complete' | 'active' | 'pending';
  }> | undefined) || [];
  const ingestStats = message.metadata?.ingest_stats as {
    totalFiles?: number;
    processedFiles?: number;
    totalChunks?: number;
    totalSymbols?: number;
    progressPercent?: number;
  } | undefined;

  // Check if content has progress steps (emoji format) or from streaming metadata
  const progressSteps = useMemo(() => {
    // First check for progress_steps from streaming (stored in metadata)
    const metadataSteps = message.metadata?.progress_steps as Array<{
      step: string;
      phase: string;
      message?: string;
      status: 'complete' | 'active' | 'pending';
    }> | undefined;

    if (metadataSteps && metadataSteps.length > 0) {
      return metadataSteps;
    }

    // Fall back to parsing from content (emoji format)
    if (!hasContent) return null;
    return parseProgressSteps(message.content);
  }, [hasContent, message.content, message.metadata?.progress_steps]);

  // Strip emoji progress steps from content if we have them in metadata
  const displayContent = useMemo(() => {
    if (progressSteps && hasContent) {
      // We have progress steps - strip emoji format from content to avoid duplication
      return stripProgressSteps(message.content);
    }
    return message.content;
  }, [progressSteps, hasContent, message.content]);

  const hasDisplayContent = displayContent.length > 0;

  // Build URL for viewing all sources (use workflow_id to fetch from API)
  const sourcesViewUrl = hasMoreSources && workflowId
    ? `/sources?workflow_id=${workflowId}`
    : null;

  // Feature spec avatar
  const renderAvatar = () => {
    if (isUser) return null;

    if (isIngest) {
      return (
        <div className="flex-shrink-0">
          <div className={cn(
            "w-10 h-10 rounded-full flex items-center justify-center ring-2 ring-white/10",
            "bg-gradient-to-br from-slate-500 to-slate-700"
          )}>
            <FileCode className="h-5 w-5 text-white" />
          </div>
        </div>
      );
    }

    if (isPlanWorkflow) {
      return (
        <div className="flex-shrink-0">
          <div className={cn(
            "w-10 h-10 rounded-full flex items-center justify-center ring-2 ring-white/10",
            "bg-gradient-to-br from-teal-500 to-cyan-600"
          )}>
            <ClipboardList className="h-5 w-5 text-white" />
          </div>
        </div>
      );
    }

    if (isSystem) {
      return (
        <div className="flex-shrink-0">
          <div className="w-10 h-10 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center ring-2 ring-white/10">
            <span className="text-slate-600 dark:text-slate-200 font-medium">⚙️</span>
          </div>
        </div>
      );
    }

    return (
      <div className="flex-shrink-0">
        <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center ring-2 ring-blue-500/20">
          <Bot className="h-5 w-5 text-white" />
        </div>
      </div>
    );
  };

  // Render ingest message content
  const renderIngestContent = () => {
    if (isIngestError) {
      return (
        <div className="flex items-start gap-2 text-red-600 dark:text-red-400">
          <XCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <span className="text-sm">{message.content}</span>
        </div>
      );
    }

    if (isIngestComplete) {
      return (
        <div className="flex items-start gap-2 text-green-600 dark:text-green-400">
          <CheckCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <span className="text-sm font-medium">{message.content}</span>
        </div>
      );
    }

    if (isIngestProgress && ingestProgressSteps.length > 0) {
      // Build stats display
      const statsDisplay: string[] = [];
      if (ingestStats?.totalFiles) {
        statsDisplay.push(`Files: ${ingestStats.processedFiles ?? 0}/${ingestStats.totalFiles}`);
      }
      if (ingestStats?.totalChunks) {
        statsDisplay.push(`Chunks: ${ingestStats.totalChunks}`);
      }
      if (ingestStats?.totalSymbols) {
        statsDisplay.push(`Symbols: ${ingestStats.totalSymbols}`);
      }
      if (ingestStats?.progressPercent && ingestStats.progressPercent > 0) {
        statsDisplay.push(`${Math.round(ingestStats.progressPercent)}%`);
      }

      return (
        <div className="space-y-2">
          <ProgressSteps
            steps={ingestProgressSteps}
            title="Repository Ingestion"
            variant="default"
            defaultCollapsed={false}
          />
          {statsDisplay.length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-400">
              {statsDisplay.map((stat, idx) => (
                <span key={idx} className="bg-slate-100 dark:bg-slate-800/50 px-2 py-0.5 rounded">
                  {stat}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    }

    // Default content rendering
    return (
      <MarkdownRenderer
        content={message.content}
        enableMermaid={false}
        enableCodeHighlight={false}
      />
    );
  };

  // Render plan workflow content
  const renderPlanContent = () => {
    if (isPlanError) {
      const planError = usePlanStore.getState().error;
      const errorMessage = planError?.message
        || (message.metadata?.planErrorMessage as string)
        || message.content
        || 'Plan workflow encountered an error';
      return (
        <div className="flex items-start gap-2 text-red-600 dark:text-red-400">
          <XCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <span className="text-sm">{errorMessage}</span>
        </div>
      );
    }

    // Render plan completion with document download
    if (isPlanComplete) {
      const manifestPayload = message.metadata?.documentManifest
        ?? (message.metadata?.planPanel as Record<string, unknown> | undefined)?.documentManifest
        ?? message.metadata?.planDocuments
        ?? null;
      const planSessionId = (message.metadata?.planPanel as Record<string, unknown> | undefined)?.sessionId as string | undefined;

      const handleRequestRevisions = planSessionId ? () => {
        const socket = getWebSocket();
        if (socket) {
          socket.send({
            type: 'plan.navigate',
            payload: {
              session_id: planSessionId,
              target_phase: 'assembly',
              confirm_cascade: true,
            },
          });
        }
      } : undefined;

      if (manifestPayload) {
        // New format: documentManifest with entries array
        const manifest = manifestPayload as Record<string, unknown>;
        const entries = manifest.entries;
        if (Array.isArray(entries) && entries.length > 0) {
          return (
            <PlanDocumentDownload
              sessionId={planSessionId}
              manifestEntries={entries}
              composedIndexUrl={manifest.composedIndexUrl as string | undefined}
              specName={manifest.specName as string | undefined}
              onRequestRevisions={handleRequestRevisions}
            />
          );
        }
        // Old format: specDocumentUrl string
        const specUrl = manifest.specDocumentUrl as string | undefined;
        if (specUrl) {
          return (
            <PlanDocumentDownload
              sessionId={planSessionId}
              specDocumentUrl={specUrl}
              onRequestRevisions={handleRequestRevisions}
            />
          );
        }
      }
    }

    // Render from planPanel metadata (similar to wizardPanel)
    if (message.metadata?.planPanel) {
      const planMeta = message.metadata.planPanel as PlanPanelMetadata;
      const handlePhaseSubmit = (phase: string, data: Record<string, string>) => {
        const socket = getWebSocket();
        if (socket && planMeta.sessionId) {
          socket.send({
            type: 'plan.phase.input',
            payload: {
              session_id: planMeta.sessionId,
              phase,
              data,
            },
          });
        }
      };

      const handleRetry = () => {
        const socket = getWebSocket();
        if (socket && planMeta.sessionId) {
          socket.send({
            type: 'plan.retry',
            payload: {
              session_id: planMeta.sessionId,
            },
          });
        }
      };

      const handlePhaseNavigate = (targetPhase: string) => {
        setPendingNavigatePhase(targetPhase);
        const socket = getWebSocket();
        if (socket && planMeta.sessionId) {
          socket.send({
            type: 'plan.navigate',
            payload: {
              session_id: planMeta.sessionId,
              target_phase: targetPhase,
              confirm_cascade: false, // Default to false to trigger cascade warning if necessary
            },
          });
        }
      };

      const handleCascadeConfirm = () => {
        if (!pendingNavigatePhase) return;
        const socket = getWebSocket();
        if (socket && planMeta.sessionId) {
          socket.send({
            type: 'plan.navigate',
            payload: {
              session_id: planMeta.sessionId,
              target_phase: pendingNavigatePhase,
              confirm_cascade: true,
            },
          });
        }
        setPendingNavigatePhase(null);
        setCascadeWarning(null);
      };

      const handleCascadeCancel = () => {
        setPendingNavigatePhase(null);
        setCascadeWarning(null);
      };

      const handleSaveAndClose = () => {
        const socket = getWebSocket();
        if (socket && planMeta.sessionId) {
          socket.send({
            type: 'plan.pause',
            payload: {
              session_id: planMeta.sessionId,
            },
          });
        }
        router.push('/plan');
      };

      const currentPhase = planMeta.currentPhase as PlanPhaseId;
      const displayPhase = (viewingPhase ?? currentPhase) as PlanPhaseId;
      const isViewingPastPhase = viewingPhase !== null && viewingPhase !== currentPhase;
      const phaseData = planMeta.phases?.[displayPhase];

      // Build the phases Record that PlanPhaseBar expects
      const phaseStatuses = {} as Record<PlanPhaseId, 'pending' | 'in_progress' | 'complete' | 'error'>;
      for (const pid of ['context', 'research', 'planning', 'orchestrate', 'assembly'] as PlanPhaseId[]) {
        phaseStatuses[pid] = (planMeta.phases?.[pid]?.status as 'pending' | 'in_progress' | 'complete' | 'error') || 'pending';
      }

      // Calculate overall progress from completed phases
      const completedCount = Object.values(phaseStatuses).filter(s => s === 'complete').length;
      const overallProgress = completedCount / PLAN_PHASES.length;

      // Build promptData from phase data if available, preserving approval options or form fields
      const promptData = phaseData?.data as Record<string, unknown> | undefined;
      const planContextItems = planMeta?.planContextItems as Record<string, unknown> | null | undefined;
      const planArtifacts = planMeta?.planArtifacts;

      return (
        <div className="max-h-[70vh] overflow-y-auto space-y-4 pr-1">
          {cascadeWarning && cascadeWarning.affectedPhases.length > 0 && (
            <CascadeWarningBanner
              affectedPhases={cascadeWarning.affectedPhases}
              onConfirm={handleCascadeConfirm}
              onCancel={handleCascadeCancel}
            />
          )}
          <BudgetIndicator
            budget={{
              remainingLlmCalls: (planMeta.budget?.remainingLlmCalls as number) || 0,
              tokensUsed: (planMeta.budget?.tokensUsed as number) || 0,
              maxLlmCalls: (planMeta.budget?.maxLlmCalls as number) || 0,
              maxTokens: (planMeta.budget?.maxTokens as number) || 0,
              remainingPct: (planMeta.budget?.maxLlmCalls as number) > 0
                ? ((planMeta.budget?.remainingLlmCalls as number) || 0) / (planMeta.budget?.maxLlmCalls as number)
                : 0,
            }}
            workflowStatus={(planMeta.workflowStatus as string) || (messageType === 'plan_error' ? 'error' : messageType === 'plan_complete' ? 'complete' : 'running')}
            onResume={(newLimits) => {
              const socket = getWebSocket();
              if (socket && planMeta.sessionId) {
                socket.send({
                  type: 'plan.resume',
                  payload: {
                    session_id: planMeta.sessionId,
                    ...newLimits,
                  },
                });
              }
            }}
            onSaveAndClose={handleSaveAndClose}
          />
          <PlanPhaseBar
            currentPhase={currentPhase}
            phases={phaseStatuses}
            overallProgress={overallProgress}
            onPhaseClick={handlePhaseView}
            viewingPhase={viewingPhase}
          />
          {isViewingPastPhase && (
            <div className="flex items-center justify-between px-4 py-2 bg-amber-50 dark:bg-amber-900/10 border-b border-amber-200 dark:border-amber-800">
              <span className="text-xs text-amber-700 dark:text-amber-300">
                Viewing completed phase — workflow continues on the active phase
              </span>
              <button
                onClick={() => setViewingPhase(null)}
                className="text-xs text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200 underline"
              >
                Return to active phase
              </button>
            </div>
          )}
          <PlanPhasePanel
            sessionId={planMeta.sessionId}
            phase={displayPhase}
            status={phaseData?.status || 'pending'}
            planContextItems={planContextItems ?? null}
            planArtifacts={planArtifacts}
            promptData={promptData}
            agentContent={planMeta.agentContent}
            result={phaseData?.result}
            thinkingSteps={planMeta.thinkingSteps || []}
            specSection={planMeta.specSection ?? null}
            specSectionContent={planMeta.specSectionContent ?? null}
            researchSummary={planMeta.researchSummary ?? null}
            onSubmit={(data) => handlePhaseSubmit(currentPhase, data as Record<string, string>)}
            onRetry={handleRetry}
            onNavigateToPhase={handlePhaseNavigate}
            isViewingPastPhase={isViewingPastPhase}
            planTasks={planMeta.planTasks}
            circuitBreaker={planMeta.circuitBreaker}
            documentManifest={planMeta.documentManifest}
          />
        </div>
      );
    }

    // plan_start: spinner while waiting for first phase prompt
    // plan_active: plan is underway, this start message is now just a static label
    if (messageType === 'plan_active') {
      return (
        <div className="flex items-start gap-2 text-muted-foreground">
          <CheckCircle className="h-4 w-4 mt-0.5 flex-shrink-0 text-teal-500" />
          <span className="text-sm">{message.content}</span>
        </div>
      );
    }

    return (
      <div className="flex items-start gap-2">
        <Loader2 className="h-4 w-4 mt-0.5 flex-shrink-0 animate-spin text-teal-500" />
        <span className="text-sm">{message.content || 'Processing plan workflow...'}</span>
      </div>
    );
  };

  // Get message container styles
  const getMessageStyles = () => {
    if (isUser) {
      return 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-md';
    }
    if (isIngest) {
      return cn(
        'border',
        isIngestError
          ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800 text-red-900 dark:text-red-100'
          : isIngestComplete
            ? 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800 text-green-900 dark:text-green-100'
            : 'bg-slate-50 dark:bg-slate-950/30 border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100'
      );
    }
    if (isPlanWorkflow) {
      return cn(
        'border',
        isPlanError
          ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800 text-red-900 dark:text-red-100'
          : isPlanComplete
            ? 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800 text-green-900 dark:text-green-100'
            : 'bg-teal-50 dark:bg-teal-950/30 border-teal-200 dark:border-teal-800 text-teal-900 dark:text-teal-100'
      );
    }
    if (isSystem) {
      return 'bg-slate-50 text-slate-900 dark:bg-slate-900/50 dark:text-slate-100 border border-slate-200 dark:border-slate-700';
    }
    return 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100';
  };

  return (
    <div
      className={cn(
        "flex w-full gap-4",
        isUser ? 'justify-end' : 'justify-start',
        isSystem && 'opacity-80'
      )}
    >
      {renderAvatar()}

      {/* Content */}
      <div className={cn("flex-1 gap-3 min-w-0", isPlanWorkflow ? 'max-w-5xl' : 'max-w-3xl')}>
        <div className={cn('rounded-3xl p-5 shadow-sm', getMessageStyles())}>
          {/* Intent badge for assistant messages */}
          {!isUser && intent && (
            <div className="mb-3">
              <IntentBadge intent={intent} />
            </div>
          )}

          {/* Message content */}
          {message.type === 'error' ? (
            <div className="text-red-500 text-sm">{message.content}</div>
          ) : message.type === 'code' && message.content ? (
            <MarkdownRenderer
              content={`\`\`\`${message.metadata?.model?.split(':')[0] || 'typescript'}\n${message.content}\n\`\`\``}
              enableMermaid={false}
            />
          ) : message.type === 'tool_use' && message.metadata?.tool_calls ? (
            <div className="mb-3">
              <span className="text-sm font-medium text-muted-foreground uppercase">Tools used:</span>
              {message.metadata.tool_calls.map((call, idx) => {
                const resultStr = call.result ? JSON.stringify(call.result, null, 2) : null;
                return (
                  <div key={idx} className="bg-muted rounded p-2 border border-border mt-1">
                    <div className="font-medium text-sm">{call.name}</div>
                    {resultStr && (
                      <div className="text-xs text-muted-foreground mt-1">
                        Result: <pre className="whitespace-pre-wrap break-all">{resultStr}</pre>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : isIngest ? (
            renderIngestContent()
          ) : isPlanWorkflow ? (
            renderPlanContent()
          ) : isAssistant ? (
            <AssistantMessageBody
              message={message}
              displayContent={displayContent}
              hasDisplayContent={hasDisplayContent}
              isCurrentlyStreaming={isCurrentlyStreaming}
              progressSteps={progressSteps}
              mermaidDiagrams={mermaidDiagrams}
              intent={intent}
            />
          ) : isUser ? (
            /* User messages - plain text with proper contrast on blue background */
            <div className="text-white text-sm leading-relaxed whitespace-pre-wrap">{message.content}</div>
          ) : (
            <MarkdownRenderer
              content={message.content}
              enableMermaid={false}
              enableCodeHighlight={false}
            />
          )}

          {/* Source references below the answer */}
          {hasSources && !isUser && (
            <div className="mt-3 pt-3 border-t border-border">
              <div className="flex items-center justify-between gap-1.5 mb-2">
                <div className="flex items-center gap-1.5">
                  <FileCode className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    Sources ({uniqueFileCount} file{uniqueFileCount !== 1 ? 's' : ''}{totalSources !== uniqueFileCount ? `, ${totalSources} chunks` : ''})
                  </span>
                </div>
                {workflowId && (
                  <Link
                    href={`/sources?workflow_id=${workflowId}`}
                    className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                  >
                    View sources page
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {uniqueFileSources.map((source, idx) => (
                  <SourceBadge key={idx} source={source} index={idx} />
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          {message.metadata?.timestamp && (
            <div className="mt-2 text-xs text-muted-foreground">
              {new Date(message.metadata.timestamp).toLocaleString()}
              {message.metadata?.model && (
                <span className="ml-2">• {message.metadata.model}</span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

Message.displayName = 'Message';
