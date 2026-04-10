import type { SourceItem, Repository } from './api';

export type MessageRole = 'user' | 'assistant' | 'system';
export type MessageType = 'text' | 'error' | 'plan' | 'progress' | 'ingest' | 'code' | 'tool_use';

export interface MessageMetadata {
  timestamp: Date | string;
  model?: string;
  sources?: Source[];
  total_sources?: number;
  workflow_id?: string;
  mermaid_diagrams?: string[];
  intent?: string;
  isStreaming?: boolean;
  // Progress tracking
  progress_steps?: Array<{
    step: string;
    phase: string;
    message?: string;
    status: 'complete' | 'active' | 'pending';
  }>;
  progress_percent?: number;
  current_step?: number;
  total_steps?: number;
  message_type?: string;
  ingest_stats?: {
    totalFiles?: number;
    processedFiles?: number;
    totalChunks?: number;
    totalSymbols?: number;
    progressPercent?: number;
  };
  // Plan phase panel
  plan_panel?: import('@/components/plan/PlanContext').PlanPanelMetadata;
  // Tool use
  tool_calls?: Array<{ name: string; result?: unknown; [key: string]: unknown }>;
  [key: string]: unknown;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  type?: MessageType;
  content: string;
  session_id?: string;
  sources?: SourceItem[];
  mermaid_diagrams?: string[];
  workflow_id?: string;
  timestamp?: string;
  isStreaming?: boolean;
  metadata?: MessageMetadata;
}

export interface ContextEntry {
  id: string;
  repo_id?: string;
  label?: string;
  content?: string;
  type?: string;
}

export interface SpecPhaseProgressData {
  phase: string;
  step?: string;
  progress_percent?: number;
  message?: string;
  [key: string]: unknown;
}

export interface ChatSessionMeta {
  id: string;
  title: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface ChatState {
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => void;
  streamMessage: () => void;
  clearChat: () => void;
  isStreaming: boolean;
  isLoading: boolean;
  isBlocked: boolean;
  specPhaseProgress: SpecPhaseProgressData | null;
  currentModel: string;
  selectModel: (model: string) => void;
  contexts: Map<string, ContextEntry[]>;
  selectedContexts: string[];
  addContext: (context: ContextEntry) => void;
  removeContext: (id: string) => void;
  toggleContext: (id: string) => void;
  executeCommand: (command: string) => Promise<void>;
  sendWorkflowInput: (workflowId: string, payload: Record<string, unknown>) => void;
  repositories: Repository[];
  selectedRepoId: string | null;
  setSelectedRepoId: (id: string | null) => void;
  // Session management
  createNewChat: () => void;
  switchChat: (sessionId: string) => void;
  deleteChat: (sessionId: string) => void;
  renameChat: (sessionId: string, title: string) => void;
  activeSessionId: string | null;
  sessions: ChatSessionMeta[];
  // Plan name prompt
  planNameDialogOpen: boolean;
  startPlanWithName: (name: string) => void;
  cancelPlanNameDialog: () => void;
  error?: string | null;
}

export interface Command {
  name: string;
  description: string;
  pattern?: RegExp | string;
  examples?: string[];
  handler?: () => void;
}

export interface Source {
  file_path: string;
  start_line?: number | null;
  end_line?: number | null;
  content?: string | null;
  symbol?: string | null;
  score?: number | null;
}
