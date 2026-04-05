import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { PlanDocumentDownload } from '../PlanDocumentDownload';
import { usePlanStore } from '@/lib/store/planStore';

describe('PlanDocumentDownload session ownership', () => {
  const originalFetch = global.fetch;
  const originalCreateObjectUrl = URL.createObjectURL;
  const originalRevokeObjectUrl = URL.revokeObjectURL;

  beforeEach(() => {
    usePlanStore.setState({ sessionId: 'stale-session-id' });
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        content: '# Final Spec',
        content_type: 'text/markdown',
      }),
    }) as jest.Mock;
    URL.createObjectURL = jest.fn(() => 'blob:test');
    URL.revokeObjectURL = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
  });

  it('downloads with the owning message session instead of the stale global plan session', async () => {
    render(
      <PlanDocumentDownload
        sessionId="correct-plan-session"
        specDocumentUrl="output/final_spec.md"
        specName="FedEx"
      />,
    );

    fireEvent.click(screen.getByText('Download Spec Document'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/plan/sessions/correct-plan-session/artifacts/output/final_spec.md',
      );
    });
  });
});
