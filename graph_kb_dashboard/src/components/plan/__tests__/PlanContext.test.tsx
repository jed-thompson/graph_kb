import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';

import { PlanContextProvider, usePlanContext } from '../PlanContext';

function SubmitHarness() {
  const { onSubmit } = usePlanContext();

  return (
    <button onClick={() => onSubmit({ decision: 'approve' })}>
      Submit
    </button>
  );
}

describe('PlanContextProvider prompt identity', () => {
  it('re-attaches interrupt identity when submitting prompt responses', () => {
    const onSubmit = jest.fn();

    render(
      <PlanContextProvider
        sessionId="session-1"
        phase="assembly"
        status="in_progress"
        promptData={{
          type: 'approval',
          interrupt_id: 'interrupt-1',
          task_id: 'task-1',
          options: [{ id: 'approve', label: 'Approve' }],
        }}
        thinkingSteps={[]}
        onSubmit={onSubmit}
        onRetry={() => {}}
      >
        <SubmitHarness />
      </PlanContextProvider>,
    );

    fireEvent.click(screen.getByText('Submit'));

    expect(onSubmit).toHaveBeenCalledWith({
      decision: 'approve',
      interrupt_id: 'interrupt-1',
      task_id: 'task-1',
    });
  });
});
