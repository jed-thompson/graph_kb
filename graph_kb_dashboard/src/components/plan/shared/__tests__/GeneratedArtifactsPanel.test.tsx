import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { GeneratedArtifactsPanel } from '../GeneratedArtifactsPanel';

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

jest.mock('@/components/ui/collapsible', () => ({
  CollapsibleSection: ({
    title,
    children,
  }: {
    title: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div>
      <div>{title}</div>
      <div>{children}</div>
    </div>
  ),
}));

jest.mock('@/components/chat/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

const { getPlanArtifact } = jest.requireMock('@/lib/api/planArtifacts') as {
  getPlanArtifact: jest.Mock;
};

describe('GeneratedArtifactsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders JSON-array artifacts using structured sections instead of a raw blob', async () => {
    getPlanArtifact.mockResolvedValue({
      content: JSON.stringify([
        {
          doc_id: 'c5da9780-57ab-47dc-9228-b6156d6e3c41',
          filename: 'reference_0_developer.fedex.com_api_en-us_catalog_ltl-freight_v1_docs.html.txt',
          role: 'supporting',
          sections: [
            { heading: 'Introduction', token_count: 79 },
            { heading: 'How Freight LTL API works', token_count: 1183 },
          ],
        },
      ]),
      content_type: 'application/json',
    });

    render(
      <GeneratedArtifactsPanel
        sessionId="plan-session-1"
        artifacts={[
          {
            key: 'context/document_section_index.json',
            summary: 'Composite document section index for per-task loading',
            size_bytes: 1123,
            created_at: '2026-04-01T00:00:00Z',
            content_type: 'application/json',
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByText('Context Gathering'));
    fireEvent.click(await screen.findByText('Composite document section index for per-task loading'));

    await waitFor(() => {
      expect(getPlanArtifact).toHaveBeenCalledWith(
        'plan-session-1',
        'context/document_section_index.json',
      );
    });

    expect((await screen.findAllByText('reference_0_developer.fedex.com_api_en-us_catalog_ltl-freight_v1_docs.html.txt')).length).toBeGreaterThan(0);
    expect(await screen.findByText('Doc Id')).toBeInTheDocument();
    expect(await screen.findByText('Filename')).toBeInTheDocument();
    expect(await screen.findByText('Sections')).toBeInTheDocument();
    expect(screen.queryByText(/\[\{"doc_id":/i)).not.toBeInTheDocument();
  });

  it('renders composed document indexes with a structured table of contents layout', async () => {
    getPlanArtifact.mockResolvedValue({
      content: `# Document Suite Index: FedEx

**Total Documents:** 12
**Total Tokens:** 38664

## Table of Contents

- [OK] **JSON API Collection** (\`spec_section_examples_and_developer_docs\`) — 4289 tokens
- [OK] **How Freight LTL API works** (\`spec_section_rate_freight_ltl_operation\`) — 3152 tokens

## Cross-Reference Map

No inter-document dependencies detected.`,
      content_type: 'text/markdown',
    });

    render(
      <GeneratedArtifactsPanel
        sessionId="plan-session-1"
        artifacts={[
          {
            key: 'output/index.md',
            summary: 'Composed document index for FedEx',
            size_bytes: 1303,
            created_at: '2026-04-02T00:00:00Z',
            content_type: 'text/markdown',
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByText('Assembly'));
    fireEvent.click(await screen.findByText('Composed document index for FedEx'));

    await waitFor(() => {
      expect(getPlanArtifact).toHaveBeenCalledWith(
        'plan-session-1',
        'output/index.md',
      );
    });

    expect(await screen.findByText('Document Suite Index')).toBeInTheDocument();
    expect(await screen.findByText('FedEx')).toBeInTheDocument();
    expect(await screen.findByText('Table of Contents')).toBeInTheDocument();
    expect(await screen.findByText('JSON API Collection')).toBeInTheDocument();
    expect(await screen.findByText('spec_section_examples_and_developer_docs')).toBeInTheDocument();
    expect(await screen.findByText('4,289 tokens')).toBeInTheDocument();
    expect(await screen.findByText('Cross-Reference Map')).toBeInTheDocument();
    expect(screen.queryByText(/\[OK\].*JSON API Collection/i)).not.toBeInTheDocument();
  });
});
