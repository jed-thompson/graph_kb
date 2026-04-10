import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ChatMessage, MessageMetadata } from '@/lib/types/chat';

// ---------------------------------------------------------------------------
// Session types
// ---------------------------------------------------------------------------
export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

/** Lightweight summary used in UI lists. */
export interface ChatSessionMeta {
  id: string;
  title: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------
interface ChatStore {
  sessions: ChatSession[];
  activeSessionId: string | null;
  _hasHydrated: boolean;

  // Session management
  createSession: (repoId?: string | null) => string;
  deleteSession: (id: string) => void;
  setActiveSession: (id: string) => void;
  getActiveSession: () => ChatSession | undefined;
  updateSessionTitle: (id: string, title: string) => void;

  // Message management (operates on active session)
  addMessage: (msg: ChatMessage) => void;
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void;
  clearMessages: () => void;

  // Compat fields kept for legacy callers
  messages: ChatMessage[];
  isLoading: boolean;
  selectedRepoId: string | null;
  setLoading: (loading: boolean) => void;
  setSelectedRepoId: (repoId: string | null) => void;

  setHasHydrated: (v: boolean) => void;
}

function makeSession(repoId?: string | null): ChatSession {
  const id = `session-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const now = new Date().toISOString();
  return { id, title: 'New Chat', messages: [], createdAt: now, updatedAt: now };
}

// ---------------------------------------------------------------------------
// Persistence helpers
//
// All size-reduction logic lives here in partialize, NOT in a custom storage
// wrapper. This keeps the storage layer as a thin pass-through to localStorage
// via createJSONStorage — no custom serialization, no API mismatch risk.
// ---------------------------------------------------------------------------
const MAX_PERSISTED_SESSIONS = 20;
const MAX_MESSAGES_PER_SESSION = 100;
const MAX_SOURCES_PER_MESSAGE = 5;

/** Strip heavy metadata fields that are reconstructed from WebSocket on reload. */
function stripMessageForPersistence(msg: ChatMessage): ChatMessage {
  if (!msg.metadata) return msg;

  const meta: Record<string, unknown> = { ...msg.metadata };

  // Plan panel metadata can be megabytes — keep only the summary fields.
  // Full data is reconstructed from plan.reconnect WebSocket events.
  for (const key of ['planPanel', 'plan_panel'] as const) {
    const panel = meta[key] as Record<string, unknown> | undefined;
    if (panel) {
      meta[key] = {
        sessionId: panel.sessionId,
        currentPhase: panel.currentPhase,
        workflowStatus: panel.workflowStatus,
      };
    }
  }

  // Strip large source content arrays
  if (Array.isArray(meta.sources) && meta.sources.length > MAX_SOURCES_PER_MESSAGE) {
    meta.sources = (meta.sources as Record<string, unknown>[])
      .slice(0, MAX_SOURCES_PER_MESSAGE)
      .map((s) => ({ ...s, content: undefined }));
  }

  // Drop bulky ingest stats
  delete meta.ingest_stats;

  return { ...msg, metadata: meta as MessageMetadata };
}

/** Trim sessions to fit within localStorage budget. */
function trimSessionsForPersistence(sessions: ChatSession[], activeSessionId: string | null): ChatSession[] {
  // Keep only recent sessions
  let trimmed = sessions.length > MAX_PERSISTED_SESSIONS
    ? sessions.slice(-MAX_PERSISTED_SESSIONS)
    : [...sessions];

  // Ensure the active session is always included even if it's old
  if (activeSessionId && !trimmed.some((s) => s.id === activeSessionId)) {
    const active = sessions.find((s) => s.id === activeSessionId);
    if (active) trimmed = [active, ...trimmed];
  }

  // Cap messages per session and strip heavy metadata
  return trimmed.map((sess) => ({
    ...sess,
    messages: sess.messages
      .slice(-MAX_MESSAGES_PER_SESSION)
      .map(stripMessageForPersistence),
  }));
}

// ---------------------------------------------------------------------------
// Storage — use createJSONStorage with plain localStorage. No custom wrapper.
//
// Why this matters: Zustand v4 persist has two internal code paths:
//   - oldImpl: triggered by getStorage/serialize/deserialize options (v3 API)
//   - newImpl: triggered by storage option (v4 API)
//
// newImpl expects storage.setItem to receive a JS object {state, version}.
// createJSONStorage wraps a raw string-based StateStorage (like localStorage)
// and handles JSON.stringify/parse so the contract is satisfied.
//
// Passing a raw {getItem, setItem, removeItem} directly as `storage` causes
// newImpl to pass objects to setItem, which localStorage.setItem coerces via
// .toString() → "[object Object]" — silently destroying all persisted data.
//
// NEVER pass a custom storage object directly. Always wrap with createJSONStorage.
// ---------------------------------------------------------------------------
const STORAGE_KEY = 'graphkb-chat-store';
const STORE_VERSION = 1;

function getStorage() {
  if (typeof window === 'undefined') {
    // SSR: return a no-op storage that won't throw.
    // Zustand will re-hydrate on the client where localStorage exists.
    return {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
  return localStorage;
}

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,
      _hasHydrated: false,

      // Legacy compat
      messages: [],
      isLoading: false,
      selectedRepoId: null,

      createSession: (repoId) => {
        const session = makeSession(repoId);
        set((s) => ({
          sessions: [...s.sessions, session],
          activeSessionId: s.activeSessionId ?? session.id,
        }));
        return session.id;
      },

      deleteSession: (id) => {
        set((s) => {
          const sessions = s.sessions.filter((sess) => sess.id !== id);
          const activeSessionId =
            s.activeSessionId === id
              ? (sessions[sessions.length - 1]?.id ?? null)
              : s.activeSessionId;
          return { sessions, activeSessionId };
        });
      },

      setActiveSession: (id) => set({ activeSessionId: id }),

      getActiveSession: () => {
        const { sessions, activeSessionId } = get();
        return sessions.find((s) => s.id === activeSessionId);
      },

      updateSessionTitle: (id, title) => {
        set((s) => ({
          sessions: s.sessions.map((sess) =>
            sess.id === id ? { ...sess, title, updatedAt: new Date().toISOString() } : sess,
          ),
        }));
      },

      addMessage: (msg) => {
        const { activeSessionId, sessions } = get();
        const targetId = activeSessionId ?? sessions[sessions.length - 1]?.id;
        if (!targetId) return;
        set((s) => ({
          sessions: s.sessions.map((sess) =>
            sess.id === targetId
              ? {
                  ...sess,
                  messages: [...sess.messages, msg],
                  updatedAt: new Date().toISOString(),
                }
              : sess,
          ),
          activeSessionId: s.activeSessionId ?? targetId,
        }));
      },

      updateMessage: (id, updates) => {
        const { activeSessionId, sessions } = get();
        // Search all sessions for the message — it may belong to a non-active
        // session (e.g., plan messages restored via reconnect)
        let targetId = activeSessionId;
        if (targetId) {
          const activeSession = sessions.find((s) => s.id === targetId);
          if (activeSession && !activeSession.messages.some((m) => m.id === id)) {
            const ownerSession = sessions.find((s) => s.messages.some((m) => m.id === id));
            if (ownerSession) targetId = ownerSession.id;
          }
        } else {
          const ownerSession = sessions.find((s) => s.messages.some((m) => m.id === id));
          targetId = ownerSession?.id ?? null;
        }
        if (!targetId) return;
        set((s) => ({
          sessions: s.sessions.map((sess) =>
            sess.id === targetId
              ? {
                  ...sess,
                  messages: sess.messages.map((m) =>
                    m.id === id ? { ...m, ...updates } : m,
                  ),
                  updatedAt: new Date().toISOString(),
                }
              : sess,
          ),
        }));
      },

      clearMessages: () => {
        const { activeSessionId } = get();
        if (!activeSessionId) return;
        set((s) => ({
          sessions: s.sessions.map((sess) =>
            sess.id === activeSessionId
              ? { ...sess, messages: [], updatedAt: new Date().toISOString() }
              : sess,
          ),
        }));
      },

      setLoading: (isLoading) => set({ isLoading }),
      setSelectedRepoId: (selectedRepoId) => set({ selectedRepoId }),
      setHasHydrated: (v) => set({ _hasHydrated: v }),
    }),
    {
      name: STORAGE_KEY,
      version: STORE_VERSION,
      storage: createJSONStorage(getStorage),

      // ── What gets persisted ──────────────────────────────────────
      // All size reduction happens here, not in a custom storage layer.
      // This keeps the storage contract simple: string in, string out.
      partialize: (state) => ({
        sessions: trimSessionsForPersistence(state.sessions, state.activeSessionId),
        activeSessionId: state.activeSessionId,
        selectedRepoId: state.selectedRepoId,
      }),

      // ── Schema migration ─────────────────────────────────────────
      // Bump STORE_VERSION when the persisted shape changes.
      // Without this, Zustand silently drops data when version mismatches.
      migrate: (persisted, version) => {
        // v0 → v1: no structural change, just adding version tracking.
        // Future migrations go here as version checks.
        return persisted as Record<string, unknown>;
      },

      // ── Post-hydration cleanup ───────────────────────────────────
      onRehydrateStorage: () => (state) => {
        if (state) {
          // Clear stale isStreaming flags from messages that were mid-stream
          // when the page was refreshed — prevents stuck loading indicators.
          let dirty = false;
          for (const sess of state.sessions) {
            for (let i = 0; i < sess.messages.length; i++) {
              const msg = sess.messages[i];
              if (msg.metadata && (msg.metadata as Record<string, unknown>).isStreaming) {
                sess.messages[i] = {
                  ...msg,
                  metadata: { ...msg.metadata, isStreaming: false },
                };
                dirty = true;
              }
            }
          }
          if (dirty) {
            useChatStore.setState({ sessions: [...state.sessions] });
          }
        }
        // Always mark hydration complete, even if state is null (empty store).
        // This unblocks the ChatContext init effect.
        state?.setHasHydrated(true);
      },
    },
  ),
);

// ---------------------------------------------------------------------------
// Selector hooks
// ---------------------------------------------------------------------------

/** Returns messages for the active session, deserialising Date strings. */
export function useActiveSessionMessages(): ChatMessage[] {
  return useChatStore((s) => {
    const active = s.sessions.find((sess) => sess.id === s.activeSessionId);
    if (!active) return [];
    return active.messages.map((m) => ({
      ...m,
      metadata: m.metadata
        ? {
            ...m.metadata,
            timestamp:
              m.metadata.timestamp instanceof Date
                ? m.metadata.timestamp
                : new Date(m.metadata.timestamp as string),
          }
        : m.metadata,
    }));
  });
}

/** Returns true once the persisted store has rehydrated from localStorage. */
export function useChatStoreHydrated(): boolean {
  return useChatStore((s) => s._hasHydrated);
}
