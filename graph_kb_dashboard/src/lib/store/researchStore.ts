import { create } from 'zustand';
import type { UploadedDocument, ResearchContextCard, ResearchFindings, ResearchRisk, RepoRelationship, ExecutionStrategy, PerRepoFindings, CrossRepoSynthesis, RepoHitlPause } from '@/lib/types/research';

export type ResearchStatus = 'idle' | 'running' | 'reviewing' | 'complete' | 'error';
export type LlmReviewStatus = 'idle' | 'running' | 'complete' | 'error';

export interface ResearchGap {
  id: string;
  title: string;
  description: string;
  priority: 'low' | 'medium' | 'high';
  answer?: string;
}

export interface ProgressStep {
  timestamp: number;
  message: string;
}

export interface ResearchProgress {
  percent: number;
  phase: string;
  message: string;
  steps: ProgressStep[];
}

export interface LlmReviewResult {
  overallAssessment: 'excellent' | 'good' | 'adequate' | 'needs_improvement';
  summary: string;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
}

interface ResearchStore {
  // Input state
  selectedRepoId: string | null;
  webUrls: string[];
  uploadedDocuments: UploadedDocument[];

  // Execution state
  status: ResearchStatus;
  progress: ResearchProgress;

  // Results
  contextCards: ResearchContextCard[];
  gaps: ResearchGap[];
  findings: ResearchFindings | null;

  // LLM review
  llmReviewStatus: LlmReviewStatus;
  llmReviewResult: LlmReviewResult | null;

  // Multi-repo state
  selectedRepoIds: string[];
  relationships: RepoRelationship[];
  executionStrategy: ExecutionStrategy;
  perRepoFindings: Record<string, PerRepoFindings>;
  crossRepoSynthesis: CrossRepoSynthesis | null;
  hitlPause: RepoHitlPause | null;
  activeSessionId: string | null;

  // Actions
  setSelectedRepoId: (id: string | null) => void;
  addWebUrl: (url: string) => void;
  removeWebUrl: (url: string) => void;
  addDocument: (doc: UploadedDocument) => void;
  removeDocument: (id: string) => void;
  setStatus: (status: ResearchStatus) => void;
  setProgress: (progress: Partial<ResearchProgress>) => void;
  addProgressStep: (message: string) => void;
  setContextCards: (cards: ResearchContextCard[]) => void;
  setGaps: (gaps: ResearchGap[]) => void;
  updateGapAnswer: (gapId: string, answer: string) => void;
  setFindings: (findings: ResearchFindings | null) => void;
  setLlmReviewStatus: (status: LlmReviewStatus) => void;
  setLlmReviewResult: (result: LlmReviewResult | null) => void;
  toggleRepoSelection: (id: string) => void;
  addRelationship: (rel: RepoRelationship) => void;
  removeRelationship: (id: string) => void;
  setExecutionStrategy: (strategy: ExecutionStrategy) => void;
  setPerRepoFindings: (repoId: string, findings: PerRepoFindings) => void;
  setCrossRepoSynthesis: (synthesis: CrossRepoSynthesis | null) => void;
  setHitlPause: (pause: RepoHitlPause | null) => void;
  setActiveSessionId: (id: string | null) => void;
  reset: () => void;
}

const initialProgress: ResearchProgress = {
  percent: 0,
  phase: 'idle',
  message: '',
  steps: [],
};

export const useResearchStore = create<ResearchStore>((set) => ({
  selectedRepoId: null,
  webUrls: [],
  uploadedDocuments: [],
  status: 'idle',
  progress: initialProgress,
  contextCards: [],
  gaps: [],
  findings: null,
  llmReviewStatus: 'idle',
  llmReviewResult: null,
  selectedRepoIds: [],
  relationships: [],
  executionStrategy: 'parallel_merge',
  perRepoFindings: {},
  crossRepoSynthesis: null,
  hitlPause: null,
  activeSessionId: null,

  setSelectedRepoId: (id) => set({ selectedRepoId: id }),
  addWebUrl: (url) => set((s) => ({ webUrls: [...s.webUrls, url] })),
  removeWebUrl: (url) => set((s) => ({ webUrls: s.webUrls.filter((u) => u !== url) })),
  addDocument: (doc) => set((s) => ({ uploadedDocuments: [...s.uploadedDocuments, doc] })),
  removeDocument: (id) =>
    set((s) => ({ uploadedDocuments: s.uploadedDocuments.filter((d) => d.id !== id) })),
  setStatus: (status) => set({ status }),
  setProgress: (progress) =>
    set((s) => ({ progress: { ...s.progress, ...progress } })),
  addProgressStep: (message) =>
    set((s) => ({
      progress: {
        ...s.progress,
        steps: [...s.progress.steps, { timestamp: Date.now(), message }],
      },
    })),
  setContextCards: (contextCards) => set({ contextCards }),
  setGaps: (gaps) => set({ gaps }),
  updateGapAnswer: (gapId, answer) =>
    set((s) => ({
      gaps: s.gaps.map((g) => (g.id === gapId ? { ...g, answer } : g)),
    })),
  setFindings: (findings) => set({ findings }),
  setLlmReviewStatus: (llmReviewStatus) => set({ llmReviewStatus }),
  setLlmReviewResult: (llmReviewResult) => set({ llmReviewResult }),
  toggleRepoSelection: (id) =>
    set((s) => {
      if (s.selectedRepoIds.includes(id)) {
        return { selectedRepoIds: s.selectedRepoIds.filter((r) => r !== id) };
      }
      if (s.selectedRepoIds.length >= 5) return {};
      return { selectedRepoIds: [...s.selectedRepoIds, id] };
    }),
  addRelationship: (rel) =>
    set((s) => ({ relationships: [...s.relationships, rel] })),
  removeRelationship: (id) =>
    set((s) => ({ relationships: s.relationships.filter((r) => r.id !== id) })),
  setExecutionStrategy: (executionStrategy) => set({ executionStrategy }),
  setPerRepoFindings: (repoId, findings) =>
    set((s) => ({ perRepoFindings: { ...s.perRepoFindings, [repoId]: findings } })),
  setCrossRepoSynthesis: (crossRepoSynthesis) => set({ crossRepoSynthesis }),
  setHitlPause: (hitlPause) => set({ hitlPause }),
  setActiveSessionId: (activeSessionId) => set({ activeSessionId }),
  reset: () =>
    set({
      status: 'idle',
      progress: initialProgress,
      contextCards: [],
      gaps: [],
      findings: null,
      llmReviewStatus: 'idle',
      llmReviewResult: null,
      selectedRepoIds: [],
      relationships: [],
      executionStrategy: 'parallel_merge' as ExecutionStrategy,
      perRepoFindings: {},
      crossRepoSynthesis: null,
      hitlPause: null,
      activeSessionId: null,
    }),
}));
