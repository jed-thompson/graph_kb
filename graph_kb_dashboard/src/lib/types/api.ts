// Repository types
export type RepoStatus = 'pending' | 'cloning' | 'indexing' | 'paused' | 'ready' | 'error';

export interface Repository {
  id: string;
  git_url: string;
  branch: string;
  status: RepoStatus;
  last_indexed_at?: string | null;
  commit_sha?: string | null;
  error_message?: string | null;
}

export interface RepoListResponse {
  repos: Repository[];
  total: number;
  offset: number;
  limit: number;
}

// Document types
export interface DocumentResponse {
  id: string;
  filename: string;
  parent?: string | null;
  category?: string | null;
  content?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  storage_key?: string | null;
  indexed_for_search?: boolean | null;
  file_size?: number | null;
  mime_type?: string | null;
}

export interface DocumentListResponse {
  documents: DocumentResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface DocumentFilterOptions {
  parents: string[];
  categories: string[];
}

// Graph / Visualization types
export type VisualizationType = 'architecture' | 'calls' | 'dependencies' | 'full' | 'comprehensive' | 'call_chain' | 'hotspots';

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  file_path?: string | null;
  metadata?: Record<string, unknown> | null;
  x?: number;
  y?: number;
  start_line?: number | null;
  end_line?: number | null;
  signature?: string | null;
  docstring?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  metadata?: Record<string, unknown> | null;
}

export interface VisualizationResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  html?: string | null;
  viz_type: string;
  metadata?: Record<string, unknown> | null;
}

// Analysis types
export interface GraphStats {
  total_nodes: number;
  total_edges: number;
  node_counts: Record<string, number>;
  edge_counts: Record<string, number>;
  depth_analysis?: Record<string, number>;
  symbol_kinds?: Record<string, number>;
}

export interface Hotspot {
  file_path: string;
  symbol_name: string;
  complexity: number;
  incoming_calls: number;
  outgoing_calls: number;
  change_frequency: number;
}

export interface EntryPoint {
  symbol_id: string;
  name: string;
  file_path: string;
  type: string;
  description: string;
  score: number;
}

// Search / context types
export interface ContextItem {
  id: string;
  file_path: string;
  start_line?: number | null;
  end_line?: number | null;
  content: string;
  symbol?: string | null;
  score: number;
  source: string;
}

// Settings types
export interface Settings {
  top_k: number;
  max_depth: number;
  model: string;
  temperature: number;
  auto_review: boolean;
  plan_max_llm_calls: number;
  plan_max_tokens: number;
  plan_max_wall_clock_s: number;
  multi_repo_concurrency_limit: number;
}

export interface SettingsUpdateRequest {
  top_k?: number;
  max_depth?: number;
  model?: string;
  temperature?: number;
  auto_review?: boolean;
  plan_max_llm_calls?: number;
  plan_max_tokens?: number;
  plan_max_wall_clock_s?: number;
  multi_repo_concurrency_limit?: number;
}

export interface ModelOption {
  id: string;
  name: string;
  group: string;
}

export interface ModelsResponse {
  models: ModelOption[];
  current: string;
}

// MCP types
export interface MCPServerConfig {
  id: string;
  name: string;
  transport: string;
  url?: string | null;
  command?: string | null;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  tools_filter: string[];
}

export interface MCPSettingsResponse {
  servers: MCPServerConfig[];
  enabled: boolean;
}

// Source item (used in chat)
export interface SourceItem {
  file_path: string;
  start_line?: number | null;
  end_line?: number | null;
  content?: string | null;
  symbol?: string | null;
  score?: number | null;
}

// WebSocket message types
export interface LegacyWSMessage {
  type: string;
  payload?: unknown;
  [key: string]: unknown;
}

export type V3WorkflowAction = 'approve' | 'reject' | 'skip' | 'cancel' | string;

export interface WorkflowProgress {
  type: 'progress';
  step?: string;
  phase?: string;
  progress_percent?: number;
  message?: string;
  current_step?: number;
  total_steps?: number;
  files?: number;
  processed_files?: number;
  current_file?: string;
  total_files?: number;
  chunks?: number;
  total_chunks?: number;
  symbols?: number;
  total_symbols?: number;
  [key: string]: unknown;
}

export interface WorkflowResult {
  type: 'result' | 'complete';
  [key: string]: unknown;
}

export interface WorkflowError {
  type: 'error';
  error?: string;
  message?: string;
  [key: string]: unknown;
}

export interface WorkflowPreview {
  type: 'preview';
  [key: string]: unknown;
}
