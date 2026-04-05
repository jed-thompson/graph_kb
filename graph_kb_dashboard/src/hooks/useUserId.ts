const STORAGE_KEY = 'graphkb-user-id';

let cachedId: string | null = null;

function generateId(): string {
  // Simple UUID v4 generation (no crypto.randomUUID dependency)
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Get or create a persistent browser UUID identity. Safe for non-React contexts. */
export function getUserId(): string {
  if (cachedId) return cachedId;
  if (typeof window === 'undefined') return '';
  cachedId = localStorage.getItem(STORAGE_KEY);
  if (!cachedId) {
    cachedId = generateId();
    localStorage.setItem(STORAGE_KEY, cachedId);
  }
  return cachedId;
}


