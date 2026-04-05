// Custom hook: useWebSocket
// Provides easy access to WebSocket context values

'use client';

import { useWebSocket as useWebSocketContext } from '@/context/WebSocketContext';
import type { LegacyWSMessage, V3WorkflowAction } from '@/lib/types/api';
import type { IngestionProgress, WSOutgoingMessage } from '@/context/WebSocketContext';

export type { IngestionProgress };

export function useWebSocket() {
  const context = useWebSocketContext();

  if (!context) {
    console.warn('useWebSocket must be used within a WebSocketProvider');
    return {
      currentWorkflow: {
        id: '',
        type: '',
        status: 'idle' as const,
      },
      isConnected: false,
      isIngestWorkflow: false,
      isInAskCodeWorkflow: false,
      ingestionProgress: null as IngestionProgress | null,
      preview: null,
      lastMessage: null as Record<string, unknown> | null,
      startIngest: (_gitUrl: string, _branch?: string) => {},
      startAskCode: (_query: string, _repoId: string) => {},
      cancelWorkflow: () => {},
      sendCancel: (_workflowId: string) => {},
      sendReconnect: (_workflowId: string) => {},
      sendAction: (_action: 'pause' | 'resume') => {},
      sendInput: (_threadId: string, _decision: V3WorkflowAction) => {},
      sendMessage: (_message: LegacyWSMessage | WSOutgoingMessage | Record<string, unknown>) => {},
    };
  }

  const { currentWorkflow, sendMessage, ws } = context;

  return {
    currentWorkflow,
    isConnected: context.isConnected,
    isIngestWorkflow: currentWorkflow?.type === 'ingest',
    isInAskCodeWorkflow: currentWorkflow?.type === 'ask-code',
    ingestionProgress: context.ingestionProgress,
    preview: context.preview,
    lastMessage: context.lastMessage,
    startIngest: (gitUrl: string, branch?: string) => {
      const message: LegacyWSMessage = {
        type: 'start',
        payload: {
          workflow_type: 'ingest',
          git_url: gitUrl,
          branch,
        },
      };
      sendMessage(message);
    },
    startAskCode: (query: string, repoId: string) => {
      const message: LegacyWSMessage = {
        type: 'start',
        payload: {
          workflow_type: 'ask-code',
          query,
          repo_id: repoId,
        },
      };
      sendMessage(message);
    },
    cancelWorkflow: () => {
      ws?.cancelWorkflow();
    },
    sendCancel: context.sendCancel,
    sendReconnect: context.sendReconnect,
    sendAction: context.sendAction,
    sendInput: context.sendInput,
    sendMessage: context.sendMessage,
  };
}
