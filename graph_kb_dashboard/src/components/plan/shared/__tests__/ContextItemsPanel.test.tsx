import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ContextItemsPanel } from '../ContextItemsPanel';

jest.mock('@/lib/api/planDocuments', () => ({
  listPlanDocuments: jest.fn(),
  downloadPlanDocument: jest.fn(),
}));

jest.mock('@/lib/api/documents', () => ({
  getDocument: jest.fn(),
}));

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

const { listPlanDocuments, downloadPlanDocument } = jest.requireMock('@/lib/api/planDocuments') as {
  listPlanDocuments: jest.Mock;
  downloadPlanDocument: jest.Mock;
};

const { getDocument } = jest.requireMock('@/lib/api/documents') as {
  getDocument: jest.Mock;
};

describe('ContextItemsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('falls back to the global documents API for existing selected documents', async () => {
    listPlanDocuments.mockResolvedValue({ documents: [], total: 0 });
    downloadPlanDocument.mockRejectedValue(new Error('Request failed with status code 404'));
    getDocument.mockResolvedValue({
      id: 'existing-doc-id',
      filename: 'fedex-carrier-integration-spec.md',
      content: '# FedEx Carrier Integration',
      created_at: new Date().toISOString(),
    });

    render(
      <ContextItemsPanel
        sessionId="plan-session-1"
        contextItems={{
          primary_document_id: 'existing-doc-id',
        }}
      />,
    );

    fireEvent.click(await screen.findByText('existing-doc-id'));

    await waitFor(() => {
      expect(downloadPlanDocument).toHaveBeenCalledWith('plan-session-1', 'existing-doc-id');
    });

    await waitFor(() => {
      expect(getDocument).toHaveBeenCalledWith('existing-doc-id');
    });

    expect(await screen.findByText('fedex-carrier-integration-spec.md')).toBeInTheDocument();
    expect(await screen.findByText('# FedEx Carrier Integration')).toBeInTheDocument();
  });
});
