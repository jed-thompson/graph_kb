'use client';

import { useCallback } from 'react';
import { useResearchStore } from '@/lib/store/researchStore';
import { useMultiRepoResearch } from './useMultiRepoResearch';

export function useResearchLauncher(onStartSingleRepo: () => void) {
  const selectedRepoIds = useResearchStore((s) => s.selectedRepoIds);
  const { startMultiRepoResearch } = useMultiRepoResearch();

  const startResearch = useCallback(() => {
    if (selectedRepoIds.length === 0) return;
    if (selectedRepoIds.length > 1) {
      startMultiRepoResearch();
    } else {
      onStartSingleRepo();
    }
  }, [selectedRepoIds, onStartSingleRepo, startMultiRepoResearch]);

  return { startResearch };
}
