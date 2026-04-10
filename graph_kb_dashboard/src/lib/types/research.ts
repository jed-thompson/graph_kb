export interface ResearchRisk {
  id?: string;
  title: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  category?: string;
  mitigation?: string;
}

export interface ResearchGap {
  id: string;
  title: string;
  description: string;
  priority: 'low' | 'medium' | 'high';
  category?: 'scope' | 'technical' | 'constraint' | 'stakeholder';
  question?: string;
  context?: string;
  impact?: 'high' | 'medium' | 'low';
  suggestedAnswers?: string[];
}

export interface CardFeedback {
  comment: string;
  rating: 'helpful' | 'not_helpful' | 'needs_revision';
}

export interface ResearchContextCard {
  id: string;
  title: string;
  content: string;
  source?: string;
  sourceType: 'web' | 'document' | 'repository' | 'generated';
  sourceName?: string;
  sourceUrl?: string;
  relevanceScore: number;
  relevance_score?: number;
  tags?: string[];
  feedback?: CardFeedback | null;
}

export interface ResearchFindings {
  summary: string;
  confidenceScore: number;
  keyInsights: string[];
  risks: ResearchRisk[];
  gaps: ResearchGap[];
  recommendations: string[];
  context_cards: ResearchContextCard[];
}

export interface UploadedDocument {
  id: string;
  filename: string;
  size: number;
  mimeType: string;
  uploadedAt: string;
  category?: string | null;
  parent?: string | null;
  indexedForSearch?: boolean | null;
}

export type RelationshipType = 'dependency' | 'rest' | 'grpc';
export type ExecutionStrategy = 'parallel_merge' | 'dependency_aware';

export interface RepoRelationship {
  id: string;
  sourceRepoId: string;
  targetRepoId: string;
  relationshipType: RelationshipType;
}

export interface ApiContractGap {
  id: string;
  sourceRepo: string;
  targetRepo: string;
  interfaceType: 'rest' | 'grpc';
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  mitigation?: string;
}

export interface DependencyIssue {
  id: string;
  upstreamRepo: string;
  downstreamRepo: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export interface CrossRepoSynthesis {
  summary: string;
  apiContractGaps: ApiContractGap[];
  crossCuttingRisks: ResearchRisk[];
  dependencyIssues: DependencyIssue[];
}

export interface PerRepoFindings {
  repoId: string;
  repoName: string;
  findings: ResearchFindings | null;
  status: 'pending' | 'running' | 'complete' | 'error';
  errorMessage?: string;
  errorPhase?: string;
  progress: number;
  phase: string;
}

export interface RepoHitlPause {
  sessionId: string;
  failedRepoId: string;
  errorMessage: string;
  phase: string;
  choices: Array<'continue' | 'retry' | 'abort'>;
}
