import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';

import { OrchestratePhase } from '../OrchestratePhase';

jest.mock('../BasePhaseContent', () => ({
  BasePhaseContent: () => <div data-testid="base-phase-content" />,
}));

jest.mock('@/components/chat/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

describe('OrchestratePhase resume hydration', () => {
  it('falls back to the active task context when transient task fields are missing', () => {
    const taskName =
      'Launch Plan: Feature Flags, Staged Rollout, Runbooks, and Operational Readiness';

    render(
      <OrchestratePhase
        status="in_progress"
        phaseInfo={{
          title: 'Orchestration',
          description: 'Executing generative tasks',
        }}
        thinkingSteps={[]}
        planTasks={{
          'task-launch': {
            id: 'task-launch',
            name: taskName,
            status: 'in_progress',
            events: [],
            specSection: taskName,
            specSectionContent: '## Launch Plan\nStage rollout behind runtime flags.',
            researchSummary:
              'Use feature flags to separate deploy from release.\n\n**Key findings:**\n• Roll out to internal users first.',
          },
        }}
        showThinking={false}
        isSubmitting={false}
        onToggleThinking={() => {}}
        onSubmit={() => {}}
      />,
    );

    expect(screen.getByText('Source Section')).toBeInTheDocument();
    expect(screen.getAllByText(taskName).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Stage rollout behind runtime flags\./),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText('Research'));

    expect(screen.getByText('Research Findings')).toBeInTheDocument();
    expect(
      screen.getByText(/Use feature flags to separate deploy from release\./),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Roll out to internal users first\./),
    ).toBeInTheDocument();
  });
});
