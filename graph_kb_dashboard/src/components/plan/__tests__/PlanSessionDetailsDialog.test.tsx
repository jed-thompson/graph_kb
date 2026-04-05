import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { PlanSessionDetailsDialog } from '../PlanSessionDetailsDialog';
import { getPlanSession } from '@/lib/api/planSessions';
import { listPlanArtifacts } from '@/lib/api/planArtifacts';

jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    open,
    children,
  }: {
    open: boolean;
    children: React.ReactNode;
  }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h1>{children}</h1>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}));

jest.mock('@/components/plan/shared/ContextItemsPanel', () => ({
  ContextItemsPanel: ({
    sessionId,
    contextItems,
  }: {
    sessionId: string;
    contextItems: unknown;
  }) => <div>{`context:${sessionId}:${contextItems ? 'loaded' : 'empty'}`}</div>,
}));

jest.mock('@/components/plan/shared/GeneratedArtifactsPanel', () => ({
  GeneratedArtifactsPanel: ({
    sessionId,
    artifacts,
  }: {
    sessionId: string;
    artifacts: Array<unknown>;
  }) => <div>{`artifacts:${sessionId}:${artifacts.length}`}</div>,
}));

jest.mock('@/lib/api/planSessions', () => ({
  getPlanSession: jest.fn(),
}));

jest.mock('@/lib/api/planArtifacts', () => ({
  listPlanArtifacts: jest.fn(),
}));

const mockGetPlanSession = getPlanSession as jest.MockedFunction<typeof getPlanSession>;
const mockListPlanArtifacts = listPlanArtifacts as jest.MockedFunction<typeof listPlanArtifacts>;

describe('PlanSessionDetailsDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('loads and renders persisted context and artifacts for a completed session', async () => {
    const onOpenInChat = jest.fn();

    mockGetPlanSession.mockResolvedValue({
      id: 'session-1',
      thread_id: 'thread-1',
      user_id: 'user-1',
      name: 'FedEx Plan',
      description: null,
      workflow_status: 'completed',
      current_phase: 'assembly',
      completed_phases: {
        context: true,
        research: true,
        planning: true,
        orchestrate: true,
        assembly: true,
      },
      budget_state: {},
      fingerprints: {},
      context_items: {
        spec_name: 'FedEx Plan',
        selected_docs: [{ id: 'doc-1', name: 'Reference' }],
      },
      created_at: '2026-04-01T00:00:00.000Z',
      updated_at: '2026-04-02T00:00:00.000Z',
    });
    mockListPlanArtifacts.mockResolvedValue({
      artifacts: [
        {
          key: 'output/final_spec.md',
          summary: 'Final spec',
          size_bytes: 2800,
          created_at: '2026-04-02T00:05:00.000Z',
          content_type: 'text/markdown',
        },
      ],
      total: 1,
    });

    render(
      <PlanSessionDetailsDialog
        open={true}
        session={{
          id: 'session-1',
          name: 'FedEx Plan',
          description: null,
          workflow_status: 'completed',
          current_phase: 'assembly',
          completed_phases: {
            context: true,
            research: true,
            planning: true,
            orchestrate: true,
            assembly: true,
          },
          budget_state: {},
          created_at: '2026-04-01T00:00:00.000Z',
          updated_at: '2026-04-02T00:00:00.000Z',
        }}
        onOpenChange={() => {}}
        onOpenInChat={onOpenInChat}
      />,
    );

    await waitFor(() => {
      expect(mockGetPlanSession).toHaveBeenCalledWith('session-1');
      expect(mockListPlanArtifacts).toHaveBeenCalledWith('session-1');
    });

    expect(await screen.findByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('context:session-1:loaded')).toBeInTheDocument();
    expect(screen.getByText('artifacts:session-1:1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /open in chat/i }));
    expect(onOpenInChat).toHaveBeenCalledWith('session-1');
  });
});
