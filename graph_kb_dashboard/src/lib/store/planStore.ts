import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { DocumentManifestEntry } from '@shared/plan-types';

export type { DocumentManifestEntry };

// ---------------------------------------------------------------------------
// Phase definitions — single source of truth
// ---------------------------------------------------------------------------
export type PlanPhaseId = 'context' | 'research' | 'planning' | 'orchestrate' | 'assembly';

export const PLAN_PHASES: PlanPhaseId[] = [
  'context',
  'research',
  'planning',
  'orchestrate',
  'assembly',
];

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------
interface PlanMessage {
  id: string;
  session_id?: string;
  [key: string]: unknown;
}

export interface CascadeWarning {
  affectedPhases: string[];
  targetPhase?: string;
  message?: string;
}

interface PlanStore {
  messages: PlanMessage[];
  activePanelId: string | null;
  sessionId: string | null;
  cascadeWarning: CascadeWarning | null;
  contextItems: Record<string, unknown> | null;
  error: { message: string } | null;
  _hasHydrated: boolean;
  addPlanMessage: (msg: PlanMessage) => void;
  updatePlanMessage: (id: string, updates: Partial<PlanMessage>) => void;
  setActivePanelId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  clearPlanMessages: () => void;
  setCascadeWarning: (warning: CascadeWarning | null) => void;
  setContextItems: (items: Record<string, unknown> | null) => void;
  setError: (error: { message: string } | null) => void;
  setHasHydrated: (v: boolean) => void;
}

export const usePlanStore = create<PlanStore>()(
  persist(
    (set) => ({
      messages: [],
      activePanelId: null,
      sessionId: null,
      cascadeWarning: null,
      contextItems: null,
      error: null,
      _hasHydrated: false,
      addPlanMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
      updatePlanMessage: (id, updates) =>
        set((state) => ({
          messages: state.messages.map((m) => (m.id === id ? { ...m, ...updates } : m)),
        })),
      setActivePanelId: (id) => set({ activePanelId: id }),
      setSessionId: (id) => set({ sessionId: id }),
      clearPlanMessages: () => set({ messages: [] }),
      setCascadeWarning: (warning) => set({ cascadeWarning: warning }),
      setContextItems: (contextItems) => set({ contextItems }),
      setError: (error) => set({ error }),
      setHasHydrated: (v) => set({ _hasHydrated: v }),
    }),
    {
      name: 'graphkb-plan-store',
      partialize: (state) => ({
        sessionId: state.sessionId,
        contextItems: state.contextItems,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);
