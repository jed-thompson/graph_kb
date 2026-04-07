'use client';

import { useCallback, useEffect, useRef } from 'react';
import { getWebSocket } from '@/lib/api/websocket';
import { useResearchStore } from '@/lib/store/researchStore';
import type { PerRepoFindings } from '@/lib/types/research';

export function useMultiRepoResearch() {
  const {
    selectedRepoIds,
    relationships,
    executionStrategy,
    perRepoFindings,
    hitlPause,
    status,
    setPerRepoFindings,
    setCrossRepoSynthesis,
    setHitlPause,
    setStatus,
  } = useResearchStore();

  const wsRef = useRef(getWebSocket());

  useEffect(() => {
    const ws = wsRef.current;

    const offRepoStarted = ws.on('research.repo.started', (data: unknown) => {
      const d = data as { repo_id: string; repo_index: number; total_repos: number };
      setPerRepoFindings(d.repo_id, {
        repoId: d.repo_id,
        repoName: d.repo_id,
        findings: null,
        status: 'running',
        progress: 0,
        phase: 'starting',
      });
    });

    const offRepoProgress = ws.on('research.repo.progress', (data: unknown) => {
      const d = data as { repo_id: string; phase: string; message: string; percent: number };
      const existing = useResearchStore.getState().perRepoFindings[d.repo_id];
      if (existing) {
        setPerRepoFindings(d.repo_id, {
          ...existing,
          progress: d.percent,
          phase: d.phase,
        });
      }
    });

    const offRepoComplete = ws.on('research.repo.complete', (data: unknown) => {
      const d = data as { repo_id: string; findings: unknown };
      const existing = useResearchStore.getState().perRepoFindings[d.repo_id];
      setPerRepoFindings(d.repo_id, {
        ...(existing ?? { repoId: d.repo_id, repoName: d.repo_id, phase: 'complete' }),
        findings: d.findings as PerRepoFindings['findings'],
        status: 'complete',
        progress: 1,
        phase: 'complete',
      });
    });

    const offRepoFailed = ws.on('research.repo.failed', (data: unknown) => {
      const d = data as { repo_id: string; error_message: string; phase: string };
      const existing = useResearchStore.getState().perRepoFindings[d.repo_id];
      setPerRepoFindings(d.repo_id, {
        ...(existing ?? { repoId: d.repo_id, repoName: d.repo_id, progress: 0 }),
        findings: null,
        status: 'error',
        phase: d.phase,
        errorMessage: d.error_message,
        errorPhase: d.phase,
      });
    });

    const offHitlPause = ws.on('research.hitl.pause', (data: unknown) => {
      const d = data as {
        session_id: string;
        failed_repo_id: string;
        error_message: string;
        phase: string;
        choices: Array<'continue' | 'retry' | 'abort'>;
      };
      setHitlPause({
        sessionId: d.session_id,
        failedRepoId: d.failed_repo_id,
        errorMessage: d.error_message,
        phase: d.phase,
        choices: d.choices,
      });
    });

    const offSynthesisStarted = ws.on('research.synthesis.started', () => {
      setStatus('running');
    });

    const offSynthesisComplete = ws.on('research.synthesis.complete', (data: unknown) => {
      const d = data as { synthesis: unknown };
      setCrossRepoSynthesis(d.synthesis as Parameters<typeof setCrossRepoSynthesis>[0]);
    });

    const offSynthesisProgress = ws.on('research.synthesis.progress', () => {
      // Progress reflected via overallProgress computed from perRepoFindings
    });

    return () => {
      offRepoStarted();
      offRepoProgress();
      offRepoComplete();
      offRepoFailed();
      offHitlPause();
      offSynthesisStarted();
      offSynthesisComplete();
      offSynthesisProgress();
    };
  }, [setPerRepoFindings, setCrossRepoSynthesis, setHitlPause, setStatus]);

  const overallProgress = (() => {
    const values = Object.values(perRepoFindings);
    if (values.length === 0) return 0;
    return values.reduce((sum, r) => sum + r.progress, 0) / values.length;
  })();

  const isRunning = Object.values(perRepoFindings).some((r) => r.status === 'running');
  const isSynthesizing =
    status === 'running' &&
    Object.values(perRepoFindings).length > 0 &&
    Object.values(perRepoFindings).every(
      (r) => r.status === 'complete' || r.status === 'error'
    );

  const respondToHitl = useCallback(
    (choice: 'continue' | 'retry' | 'abort') => {
      if (!hitlPause) return;
      wsRef.current.send({
        type: 'research.hitl.response',
        payload: { session_id: hitlPause.sessionId, choice },
      });
      setHitlPause(null);
    },
    [hitlPause, setHitlPause]
  );

  const startMultiRepoResearch = useCallback(
    (sessionQuery?: string) => {
      wsRef.current.startMultiRepoResearch({
        repo_ids: selectedRepoIds,
        relationships: relationships.map((r) => ({
          source_repo_id: r.sourceRepoId,
          target_repo_id: r.targetRepoId,
          relationship_type: r.relationshipType,
        })),
        strategy: executionStrategy,
        query: sessionQuery,
      });
      setStatus('running');
    },
    [selectedRepoIds, relationships, executionStrategy, setStatus]
  );

  return {
    startMultiRepoResearch,
    overallProgress,
    isRunning,
    isSynthesizing,
    hitlPause,
    respondToHitl,
  };
}
