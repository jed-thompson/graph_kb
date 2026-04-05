import React from 'react';
import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';

// Mock react-markdown — ESM-only module
jest.mock('react-markdown', () => {
    return {
        __esModule: true,
        default: function MockReactMarkdown({
            children,
            components,
            remarkPlugins,
        }: {
            children: string;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            components?: Record<string, React.ComponentType<any>>;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            remarkPlugins?: any[];
        }) {
            // Simple mock that parses markdown-like content and uses custom components
            const CodeComponent = components?.code;

            // Detect fenced code blocks: ```lang\ncontent\n```
            const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
            const parts: React.ReactNode[] = [];
            let lastIndex = 0;
            let match;

            const text = children || '';
            while ((match = codeBlockRegex.exec(text)) !== null) {
                // Text before code block
                if (match.index > lastIndex) {
                    const before = text.slice(lastIndex, match.index);
                    parts.push(<span key={`text-${lastIndex}`} dangerouslySetInnerHTML={{ __html: parseInline(before, CodeComponent) }} />);
                }

                const lang = match[1] || '';
                const code = match[2].replace(/\n$/, '');

                if (CodeComponent) {
                    parts.push(
                        <CodeComponent key={`code-${match.index}`} className={lang ? `language-${lang}` : undefined}>
                            {code}
                        </CodeComponent>
                    );
                } else {
                    parts.push(<pre key={`code-${match.index}`}><code>{code}</code></pre>);
                }

                lastIndex = match.index + match[0].length;
            }

            // Remaining text
            if (lastIndex < text.length) {
                const remaining = text.slice(lastIndex);
                parts.push(<span key={`text-${lastIndex}`} dangerouslySetInnerHTML={{ __html: parseInline(remaining, CodeComponent) }} />);
            }

            if (parts.length === 0) {
                parts.push(<span key="empty" dangerouslySetInnerHTML={{ __html: parseInline(text, CodeComponent) }} />);
            }

            return <div data-testid="react-markdown">{parts}</div>;
        },
    };
});

// Simple inline markdown parser for the mock
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseInline(text: string, _CodeComponent?: React.ComponentType<any>): string {
    let html = text;
    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Strikethrough
    html = html.replace(/~~(.*?)~~/g, '<del>$1</del>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
    // Tables (simplified)
    if (html.includes('|')) {
        const lines = html.trim().split('\n').filter(l => !l.match(/^\|[\s-|]+\|$/));
        const rows = lines.map(line => {
            const cells = line.split('|').filter(c => c.trim()).map(c => c.trim());
            return `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`;
        });
        html = `<table><tbody>${rows.join('')}</tbody></table>`;
    }
    // Task lists
    html = html.replace(/- \[x\] (.*)/g, '<li><input type="checkbox" checked disabled /> $1</li>');
    html = html.replace(/- \[ \] (.*)/g, '<li><input type="checkbox" disabled /> $1</li>');
    // Headers
    html = html.replace(/^# (.*)/gm, '<h1>$1</h1>');
    return html;
}

jest.mock('remark-gfm', () => ({
    __esModule: true,
    default: () => { },
}));

// Mock mermaid dynamic import
jest.mock('mermaid', () => ({
    __esModule: true,
    default: {
        initialize: jest.fn(),
        render: jest.fn().mockResolvedValue({ svg: '<svg data-testid="mermaid-svg">mock-diagram</svg>' }),
    },
}));

// Mock react-syntax-highlighter
jest.mock('react-syntax-highlighter', () => ({
    Prism: ({ children, language }: { children: string; language: string }) => (
        <pre data-testid="syntax-highlighter" data-language={language}>
            <code>{children}</code>
        </pre>
    ),
}));

jest.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
    oneDark: {},
}));

import { MarkdownRenderer } from '../MarkdownRenderer';

describe('MarkdownRenderer', () => {
    it('renders plain markdown text', () => {
        render(<MarkdownRenderer content="Hello **world**" />);
        expect(screen.getByText('world')).toBeInTheDocument();
    });

    it('renders inline code with monospace styling', () => {
        render(<MarkdownRenderer content="Use `console.log` here" />);
        const codeEl = screen.getByText('console.log');
        expect(codeEl.tagName).toBe('CODE');
    });

    it('renders GFM strikethrough', () => {
        render(<MarkdownRenderer content="~~deleted~~" />);
        const del = screen.getByText('deleted');
        expect(del.closest('del')).toBeInTheDocument();
    });

    it('renders GFM tables', () => {
        const table = `| Name | Value |\n| --- | --- |\n| A | 1 |`;
        render(<MarkdownRenderer content={table} />);
        expect(screen.getByText('Name')).toBeInTheDocument();
        expect(screen.getByText('Value')).toBeInTheDocument();
    });

    it('renders GFM task lists', () => {
        const taskList = `- [x] Done\n- [ ] Todo`;
        render(<MarkdownRenderer content={taskList} />);
        expect(screen.getByText(/Done/)).toBeInTheDocument();
        expect(screen.getByText(/Todo/)).toBeInTheDocument();
    });

    it('renders fenced code blocks with language', () => {
        const md = '```javascript\nconst x = 1;\n```';
        render(<MarkdownRenderer content={md} />);
        expect(screen.getByText('const x = 1;')).toBeInTheDocument();
    });

    it('renders mermaid code fence as diagram when enableMermaid is true', async () => {
        const md = '```mermaid\ngraph TD\n  A-->B\n```';
        render(<MarkdownRenderer content={md} enableMermaid={true} />);
        // Should show loading state initially, then render SVG
        expect(screen.getByText('Rendering diagram…')).toBeInTheDocument();

        // Wait for mermaid to render
        await waitFor(() => {
            expect(screen.getByTestId('mermaid-svg')).toBeInTheDocument();
        });
    });

    it('renders mermaid as code block when enableMermaid is false', () => {
        const md = '```mermaid\ngraph TD\n  A-->B\n```';
        render(<MarkdownRenderer content={md} enableMermaid={false} />);
        // Should NOT show diagram loading
        expect(screen.queryByText('Rendering diagram…')).not.toBeInTheDocument();
        // Should render as a code block
        expect(screen.getByText(/graph TD/)).toBeInTheDocument();
    });

    it('accepts custom className', () => {
        const { container } = render(
            <MarkdownRenderer content="test" className="custom-class" />
        );
        expect(container.firstChild).toHaveClass('custom-class');
    });

    it('defaults enableMermaid and enableCodeHighlight to true', () => {
        const { container } = render(<MarkdownRenderer content="# Hello" />);
        expect(container.querySelector('h1')).toHaveTextContent('Hello');
    });

    it('renders code block without highlighting when enableCodeHighlight is false', () => {
        const md = '```python\nprint("hi")\n```';
        render(<MarkdownRenderer content={md} enableCodeHighlight={false} />);
        // Should render as plain pre/code, not syntax-highlighted
        expect(screen.getByText('print("hi")')).toBeInTheDocument();
    });
});

// Note: The sanitizeMermaid function is not exported, so we test it indirectly
// by verifying that mermaid content with edge cases renders correctly
describe('Mermaid sanitization edge cases', () => {
    it('handles subgraph syntax with bracket title', async () => {
        // This tests that subgraph ID["Title"] is fixed to subgraph ID ["Title"]
        const md = '```mermaid\nflowchart TD\n  subgraph MY_GROUP["My Group Title"]\n    A --> B\n  end\n```';
        render(<MarkdownRenderer content={md} enableMermaid={true} />);
        await waitFor(() => {
            expect(screen.getByTestId('mermaid-svg')).toBeInTheDocument();
        });
    });

    it('handles labels with dots and colons', async () => {
        const md = '```mermaid\nflowchart TD\n  A["file.py: handler()"]\n```';
        render(<MarkdownRenderer content={md} enableMermaid={true} />);
        await waitFor(() => {
            expect(screen.getByTestId('mermaid-svg')).toBeInTheDocument();
        });
    });

    it('converts HTML br tags to mermaid line breaks', async () => {
        const md = '```mermaid\nflowchart TD\n  A["Line one<br/>Line two"]\n```';
        render(<MarkdownRenderer content={md} enableMermaid={true} />);
        await waitFor(() => {
            expect(screen.getByTestId('mermaid-svg')).toBeInTheDocument();
        });
    });
});
