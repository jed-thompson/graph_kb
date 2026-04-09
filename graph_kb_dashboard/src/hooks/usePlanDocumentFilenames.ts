import { useState, useEffect } from 'react';
import { listPlanDocuments } from '@/lib/api/planDocuments';
import { getDocument } from '@/lib/api/documents';

// Module-level cache: deduplicates concurrent fetches for the same (session, doc list).
// Multiple ContextItemsPanel instances mounted simultaneously share one in-flight request.
// The key includes primaryDocId and supportingKey so a fresh fetch is triggered when
// the document set changes (e.g. after a new upload).
const inFlightCache = new Map<string, Promise<Record<string, string>>>();

export function usePlanDocumentFilenames(
  sessionId: string | null | undefined,
  primaryDocId: string | null | undefined,
  supportingDocIds: string[]
): Record<string, string> {
  const [filenameMap, setFilenameMap] = useState<Record<string, string>>({});
  const supportingKey = supportingDocIds.join(',');

  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;

    const allDocIds = [
      ...(primaryDocId ? [primaryDocId] : []),
      ...(supportingKey ? supportingKey.split(',') : []),
    ].filter(Boolean);

    const cacheKey = `${sessionId}:${primaryDocId ?? ''}:${supportingKey}`;
    let req = inFlightCache.get(cacheKey);
    if (!req) {
      req = listPlanDocuments(sessionId)
        .then(async (res) => {
          const map: Record<string, string> = {};
          for (const doc of res.documents) {
            map[doc.id] = doc.original_filename;
          }

          // For any doc IDs not resolved by the plan endpoint (e.g. library docs
          // that pre-date the DocumentLink association fix), fall back to the
          // global /docs/{id} API which reads from ChromaDB / blob metadata.
          const missing = allDocIds.filter(id => !map[id]);
          if (missing.length > 0) {
            const results = await Promise.allSettled(
              missing.map(id => getDocument(id)),
            );
            for (let i = 0; i < missing.length; i++) {
              const result = results[i];
              if (result.status === 'fulfilled' && result.value.filename) {
                map[missing[i]] = result.value.filename;
              }
            }
          }

          return map;
        })
        .finally(() => {
          inFlightCache.delete(cacheKey);
        });
      inFlightCache.set(cacheKey, req);
    }

    req.then((map) => {
      if (!cancelled) setFilenameMap(map);
    }).catch(() => {
      // fetch failed — filenameMap stays empty, component falls back to generic labels
    });

    return () => {
      cancelled = true;
    };
  }, [sessionId, primaryDocId, supportingKey]);

  return filenameMap;
}
