import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';

import { PlanSessionListContent } from '../PlanSessionListContent';

jest.mock('../PlanSessionDetailsDialog', () => ({
  PlanSessionDetailsDialog: ({
    open,
    session,
  }: {
    open: boolean;
    session: { id: string } | null;
  }) => (open ? <div>details:{session?.id}</div> : null),
}));

describe('PlanSessionListContent', () => {
  it('renders completed sessions with a view action instead of resume', () => {
    const onResume = jest.fn();

    render(
      <PlanSessionListContent
        sessions={[
          {
            id: 'completed-session-1',
            name: 'Completed Plan',
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
          },
        ]}
        loading={false}
        error={null}
        onResume={onResume}
        onDelete={() => {}}
        onRename={() => {}}
      />,
    );

    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /view/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /resume/i })).not.toBeInTheDocument();
  });

  it('treats stale running sessions as paused in the list and still allows resume', () => {
    const onResume = jest.fn();

    render(
      <PlanSessionListContent
        sessions={[
          {
            id: 'stale-running-session',
            name: 'Paused Plan',
            description: null,
            workflow_status: 'running',
            current_phase: 'assembly',
            completed_phases: {
              context: true,
              research: true,
              planning: true,
              orchestrate: true,
            },
            budget_state: {},
            created_at: '2026-04-01T00:00:00.000Z',
            updated_at: '2026-04-01T00:00:00.000Z',
          },
        ]}
        loading={false}
        error={null}
        onResume={onResume}
        onDelete={() => {}}
        onRename={() => {}}
      />,
    );

    expect(screen.getByText('Paused')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /resume/i }));
    expect(onResume).toHaveBeenCalledWith('stale-running-session');
  });

  it('opens the details dialog for a selected session', () => {
    render(
      <PlanSessionListContent
        sessions={[
          {
            id: 'detail-session',
            name: 'Detail Plan',
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
          },
        ]}
        loading={false}
        error={null}
        onResume={() => {}}
        onDelete={() => {}}
        onRename={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /view/i }));
    expect(screen.getByText('details:detail-session')).toBeInTheDocument();
  });

  it('treats sessions with assembly already complete as completed even if status is stale', () => {
    render(
      <PlanSessionListContent
        sessions={[
          {
            id: 'stale-completed-session',
            name: 'Recovered Plan',
            description: null,
            workflow_status: 'running',
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
          },
        ]}
        loading={false}
        error={null}
        onResume={() => {}}
        onDelete={() => {}}
        onRename={() => {}}
      />,
    );

    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /view/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /resume/i })).not.toBeInTheDocument();
  });
});
