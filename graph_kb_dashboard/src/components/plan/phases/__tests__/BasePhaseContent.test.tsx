import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { BasePhaseContent } from '../BasePhaseContent';
import { PlanContextProvider } from '../../PlanContext';
import { usePlanStore } from '@/lib/store/planStore';

jest.mock('@/lib/api/planArtifacts', () => ({
  getPlanArtifact: jest.fn(),
}));

jest.mock('@/components/ui/CollapsibleCard', () => ({
  CollapsibleCard: ({
    title,
    children,
  }: {
    title: string;
    children: React.ReactNode;
  }) => (
    <div>
      <div>{title}</div>
      <div>{children}</div>
    </div>
  ),
}));

jest.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    onClick,
  }: {
    children: React.ReactNode;
    onClick?: React.MouseEventHandler<HTMLButtonElement>;
  }) => <button onClick={onClick}>{children}</button>,
}));

jest.mock('@/components/chat/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

const { getPlanArtifact } = jest.requireMock('@/lib/api/planArtifacts') as {
  getPlanArtifact: jest.Mock;
};

describe('BasePhaseContent session ownership', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    usePlanStore.setState({ sessionId: 'stale-session-id' });
  });

  it('uses the owning plan session for generated artifacts instead of the global store session', async () => {
    getPlanArtifact.mockResolvedValue({
      content: '# Research Findings',
      content_type: 'text/markdown',
    });

    render(
      <PlanContextProvider
        sessionId="correct-plan-session"
        phase="context"
        status="complete"
        planArtifacts={[
          {
            key: 'research/findings.md',
            summary: 'Research Findings',
            size_bytes: 128,
            created_at: '2026-04-01T00:00:00Z',
            content_type: 'text/markdown',
          },
        ]}
        thinkingSteps={[]}
        onSubmit={() => {}}
        onRetry={() => {}}
      >
        <BasePhaseContent
          phase="context"
          status="complete"
          phaseInfo={{
            title: 'Context',
            description: 'Context gathering',
          }}
          result={{ summary: 'Context complete' }}
          thinkingSteps={[]}
          showThinking={false}
          isSubmitting={false}
          onToggleThinking={() => {}}
          onSubmit={() => {}}
        />
      </PlanContextProvider>,
    );

    fireEvent.click(screen.getByText('Research'));
    fireEvent.click(await screen.findByText('Research Findings'));

    await waitFor(() => {
      expect(getPlanArtifact).toHaveBeenCalledWith(
        'correct-plan-session',
        'research/findings.md',
      );
    });

    expect(getPlanArtifact).not.toHaveBeenCalledWith(
      'stale-session-id',
      'research/findings.md',
    );

    expect(await screen.findByText('# Research Findings')).toBeInTheDocument();
  });
});
