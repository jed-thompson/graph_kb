import type { ChatMessage } from '@/lib/types/chat';

export function findPlanMessageBySession(messages: ChatMessage[], sessionId: string): ChatMessage | undefined {
  return messages.find(
    (m) => m.id === `plan-panel-${sessionId}` || m.session_id === sessionId,
  );
}

/**
 * 1-arg form: returns a deterministic message ID for a plan session's panel message.
 * Used when creating or updating plan panel messages.
 */
export function getPlanPanelMessageId(sessionId: string): string;

/**
 * 2-arg form: looks up the message ID from an existing message list.
 * Returns undefined if no matching message is found.
 */
export function getPlanPanelMessageId(messages: ChatMessage[], sessionId: string): string | undefined;

export function getPlanPanelMessageId(
  messagesOrSessionId: ChatMessage[] | string,
  sessionId?: string,
): string | undefined {
  if (typeof messagesOrSessionId === 'string') {
    return `plan-panel-${messagesOrSessionId}`;
  }
  return findPlanMessageBySession(messagesOrSessionId, sessionId!)?.id;
}

// ---------------------------------------------------------------------------
// Task grouping for OrchestratePhase display
// ---------------------------------------------------------------------------

export interface TaskLike {
  id: string;
  name: string;
  status: string;
  dependencies?: string[];
  events?: Array<{ timestamp: number; message: string }>;
}

export interface TaskGroup {
  key: string;
  parent: TaskLike;
  children: TaskLike[];
}

/**
 * Groups a flat list of tasks into parent/child groups based on dependency
 * relationships. Tasks that depend on exactly one other task in the list are
 * treated as children of that task.
 */
export function groupPlanTasks<T extends TaskLike>(tasks: T[]): Array<{ key: string; parent: T; children: T[] }> {
  const taskMap = new Map(tasks.map((t) => [t.id, t]));
  const childIds = new Set<string>();

  // A task is a child if it has exactly one dependency that exists in the list
  for (const task of tasks) {
    const deps = task.dependencies ?? [];
    if (deps.length === 1 && taskMap.has(deps[0])) {
      childIds.add(task.id);
    }
  }

  const groups: Array<{ key: string; parent: T; children: T[] }> = [];
  for (const task of tasks) {
    if (childIds.has(task.id)) continue; // will appear under its parent
    const children = tasks.filter(
      (t) => t.dependencies?.length === 1 && t.dependencies[0] === task.id,
    );
    groups.push({ key: task.id, parent: task, children });
  }
  return groups;
}


// ---------------------------------------------------------------------------
// Context items merge helper
// ---------------------------------------------------------------------------

type ContextItemsRecord = Record<string, unknown> | null | undefined;

/**
 * Merge context items from multiple sources with increasing priority.
 *
 * Sources (lowest → highest priority):
 *   1. Zustand plan store (form submission snapshot, persisted to localStorage)
 *   2. Existing panel metadata (from previous WebSocket events)
 *   3. Incoming backend payload (authoritative when present)
 *
 * This ensures document IDs from the form submission survive even when the
 * backend checkpoint has stale data (e.g. field aliases not yet normalized).
 */
export function mergeContextItems(
  incoming: ContextItemsRecord,
  existing: ContextItemsRecord,
  store: ContextItemsRecord,
): Record<string, unknown> | null {
  if (!incoming && !existing && !store) return null;
  return { ...(store || {}), ...(existing || {}), ...(incoming || {}) };
}
