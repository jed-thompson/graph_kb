'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { DiagramOverlay } from './DiagramOverlay';
import { Expand } from 'lucide-react';
import { CollapsibleSection } from '@/components/ui/collapsible';

interface MarkdownRendererProps {
  content: string;
  enableMermaid?: boolean;
  enableCodeHighlight?: boolean;
  className?: string;
}

/** Counter to guarantee unique IDs across all MermaidDiagram instances. */
let mermaidIdCounter = 0;

/** Track whether mermaid has been initialized globally. */
let mermaidInitialized = false;

/** Debounce delay (ms) — waits for streaming chunks to settle before rendering. */
const RENDER_DEBOUNCE_MS = 500;

/**
 * Global serial render queue. Mermaid's render() is NOT re-entrant — concurrent
 * calls corrupt each other's temporary DOM elements, causing the
 * "Cannot read properties of null (reading 'firstChild')" crash.
 * This queue ensures only one render runs at a time.
 */
const renderQueue: Array<() => Promise<void>> = [];
let queueRunning = false;

async function enqueueRender(fn: () => Promise<void>): Promise<void> {
  return new Promise<void>((resolve) => {
    renderQueue.push(async () => {
      await fn();
      resolve();
    });
    if (!queueRunning) drainQueue();
  });
}

async function drainQueue() {
  queueRunning = true;
  while (renderQueue.length > 0) {
    const next = renderQueue.shift();
    if (next) {
      try { await next(); } catch { /* handled inside fn */ }
    }
  }
  queueRunning = false;
}

/**
 * Sanitize LLM-generated mermaid so it parses correctly.
 *
 * Fixes common issues:
 * 1. <br/> / <br> / <br /> HTML tags → \n (mermaid line break)
 * 2. Unquoted [] labels containing parentheses → wrap in double-quotes
 *    e.g.  A[scripts/ (maintenance)] → A["scripts/ (maintenance)"]
 * 3. Subgraph with bracket syntax (ID["title"]) → add space before bracket
 *    e.g.  subgraph ID["title"] → subgraph ID ["title"]
 * 4. Labels with unescaped special chars (dots, colons, slashes) in brackets
 * 5. Escaped quotes inside quoted labels → remove or convert to #quot;
 *    e.g.  A["model \"name\""] → A["model name"]
 */
function sanitizeMermaid(raw: string): string {
  let s = raw.trim();
  // 1. Replace HTML line-break tags with mermaid \n
  s = s.replace(/<br\s*\/?>/gi, '\\n');
  // 2. Quote unquoted [] labels that contain ( or )
  //    Matches: ID[label with (parens)] but NOT ID["already quoted"]
  s = s.replace(
    /(\w+)\[(?!")([^\]]*\([^\]]*)\]/g,
    (_match, id, label) => `${id}["${label}"]`,
  );
  // 3. Fix subgraph syntax: subgraph ID["title"] → subgraph ID ["title"]
  //    Mermaid requires a space before the bracket in subgraph declarations
  s = s.replace(
    /subgraph\s+(\w+)\[([^\]]+)\]/gi,
    (_match, id, label) => `subgraph ${id} [${label}]`,
  );
  // 4. Quote unquoted labels containing dots, colons, or slashes
  //    These often break parsing even though they look valid
  s = s.replace(
    /(\w+)\[(?!")([^\]]*[.:\/\\][^\]]*)\]/g,
    (_match, id, label) => {
      // Skip if already properly quoted
      if (label.startsWith('"') && label.endsWith('"')) return _match;
      return `${id}["${label}"]`;
    },
  );
  // 5. Remove escaped quotes inside quoted labels
  //    Mermaid doesn't support \" inside "...", so strip them
  //    e.g. A["model \"name\""] → A["model name"]
  s = s.replace(/\\"/g, '');
  // 6. Sanitize edge labels (|...|): replace chars that break mermaid parsing.
  //    { } are used for mermaid special node types; [ ] open node label syntax.
  //    \n (literal backslash-n) is not valid in edge labels — replace with space.
  s = s.replace(/\|([^|]+)\|/g, (_match, label) => {
    const cleaned = label
      .replace(/\{/g, '(')
      .replace(/\}/g, ')')
      .replace(/\[/g, '(')
      .replace(/\]/g, ')')
      .replace(/\\n/g, ' ');
    return `|${cleaned}|`;
  });
  return s;
}

/**
 * Quick heuristic: does the chart string look like it could be complete mermaid?
 * Checks that the closing ``` fence isn't still being streamed in (the code
 * component strips it, but partial content may end mid-token).
 */
function looksComplete(chart: string): boolean {
  const trimmed = chart.trim();
  // Must have at least a diagram type keyword and one node/edge definition
  if (trimmed.length < 20) return false;
  // If it ends with an unclosed bracket, it's still streaming
  const lastChar = trimmed[trimmed.length - 1];
  if ('[({'.includes(lastChar)) return false;
  // If it ends with an arrow, more content is coming
  if (trimmed.endsWith('-->') || trimmed.endsWith('---') || trimmed.endsWith('==>')) return false;
  return true;
}

/**
 * Mermaid diagram component that lazy-loads the mermaid library client-side
 * and renders chart definitions as SVG.
 *
 * Debounces rendering to avoid hammering mermaid.render() on every streaming
 * chunk (which produces hundreds of parse errors for incomplete diagrams).
 */
export function MermaidDiagram({ chart }: { chart: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [isOverlayOpen, setIsOverlayOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Tracks whether this instance was unmounted so queued work can bail out. */
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    if (!chart?.trim()) return;

    // Clear any pending debounced render
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    // Don't even attempt if the chart is obviously incomplete
    if (!looksComplete(chart)) return;

    // Debounce: wait for chunks to settle before rendering
    timerRef.current = setTimeout(() => {
      // Enqueue the render so only one mermaid.render() runs at a time globally
      enqueueRender(async () => {
        // Bail if the component unmounted or chart changed while queued
        if (cancelledRef.current) return;

        try {
          const mermaid = (await import('mermaid')).default;

          if (!mermaidInitialized) {
            mermaid.initialize({
              startOnLoad: false,
              theme: 'dark',
              securityLevel: 'loose',
              suppressErrorRendering: true,
              flowchart: {
                curve: 'basis',
                padding: 20,
                nodeSpacing: 50,
                rankSpacing: 50,
              },
              sequence: {
                actorMargin: 50,
                boxMargin: 10,
                boxTextMargin: 5,
                noteMargin: 10,
                messageMargin: 35,
                mirrorActors: false,
                bottomMarginAdj: 1,
                useMaxWidth: true,
                rightAngles: false,
                showSequenceNumbers: false,
              },
              er: {
                useMaxWidth: true,
              },
              themeVariables: {
                primaryColor: '#6366f1',
                primaryTextColor: '#e2e8f0',
                primaryBorderColor: '#4f46e5',
                lineColor: '#64748b',
                secondaryColor: '#1e293b',
                tertiaryColor: '#0f172a',
                background: '#0f172a',
                mainBkg: '#1e293b',
                nodeBorder: '#475569',
                clusterBkg: '#1e293b',
                clusterBorder: '#475569',
                titleColor: '#e2e8f0',
                edgeLabelBackground: '#1e293b',
                fontFamily: 'Inter, system-ui, sans-serif',
                fontSize: '14px',
              },
            });
            mermaidInitialized = true;
          }

          // Sanitize common issues in LLM-generated mermaid
          const sanitized = sanitizeMermaid(chart);

          // Validate syntax FIRST — parse() doesn't touch the DOM, so it can't
          // trigger the "Cannot read properties of null (reading 'firstChild')" bug.
          const parseResult = await mermaid.parse(sanitized, { suppressErrors: true });
          if (!parseResult) {
            if (!cancelledRef.current) {
              setError('Invalid mermaid syntax');
              setSvg('');
            }
            return;
          }

          const id = `mermaid-${Date.now()}-${++mermaidIdCounter}`;

          // Clean up any orphaned elements from previous renders
          document.querySelectorAll('[id^="dmermaid-"]').forEach((el) => el.remove());
          document.getElementById(id)?.remove();

          const { svg: rendered } = await mermaid.render(id, sanitized);

          if (!cancelledRef.current) {
            setSvg(rendered);
            setError(null);
          }

          // Clean up the temp element mermaid creates
          document.getElementById(id)?.remove();
        } catch (err) {
          // Clean up broken SVG nodes mermaid v11 may leave behind
          document.querySelectorAll('[id^="dmermaid-"]').forEach((el) => el.remove());

          if (!cancelledRef.current) {
            const msg = err instanceof Error ? err.message : 'Failed to render diagram';
            console.warn('[MermaidDiagram] render failed:', msg);
            setError(msg);
            setSvg('');
          }
        }
      });
    }, RENDER_DEBOUNCE_MS);

    return () => {
      cancelledRef.current = true;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [chart]);

  if (error) {
    return (
      <div className="p-3 my-2 bg-destructive/10 border border-destructive/30 rounded text-destructive text-xs">
        <p className="font-semibold mb-1">Mermaid render error</p>
        <p className="mb-1 text-destructive/80">{error}</p>
        <pre className="whitespace-pre-wrap font-mono text-xs">{chart}</pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div ref={containerRef} className="my-2 animate-pulse bg-muted rounded p-4 flex items-center gap-2">
        <div className="w-4 h-4 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin" />
        <span className="text-muted-foreground text-sm">Rendering diagram…</span>
      </div>
    );
  }

  return (
    <>
      {/* CSS for rounded mermaid shapes */}
      <style jsx global>{`
        .mermaid-rounded rect,
        .mermaid-rounded .node rect,
        .mermaid-rounded .node circle,
        .mermaid-rounded .node ellipse,
        .mermaid-rounded .node polygon,
        .mermaid-rounded .node path,
        .mermaid-rounded .cluster rect,
        .mermaid-rounded .label rect {
          rx: 8px !important;
          ry: 8px !important;
        }
        .mermaid-rounded .edgeLabel {
          border-radius: 6px !important;
        }
        .mermaid-rounded .actor {
          border-radius: 8px !important;
        }
        .mermaid-rounded .sequenceNumber {
          border-radius: 50% !important;
        }
        .mermaid-rounded .box {
          border-radius: 8px !important;
        }
      `}</style>
      <div
        ref={containerRef}
        className="my-2 overflow-x-auto relative group cursor-pointer mermaid-rounded"
        onClick={() => setIsOverlayOpen(true)}
      >
        <div dangerouslySetInnerHTML={{ __html: svg }} />
        {/* Expand button overlay */}
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            className="p-1.5 bg-black/50 hover:bg-black/70 rounded-lg text-white"
            title="Expand diagram"
          >
            <Expand className="w-4 h-4" />
          </button>
        </div>
      </div>
      {/* Overlay */}
      <DiagramOverlay
        svg={svg}
        isOpen={isOverlayOpen}
        onClose={() => setIsOverlayOpen(false)}
      />
    </>
  );
}

/**
 * Syntax-highlighted code block that lazy-loads react-syntax-highlighter.
 */
function HighlightedCode({ language, children }: { language: string; children: string }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [Highlighter, setHighlighter] = useState<React.ComponentType<any> | null>(null);
  const [style, setStyle] = useState<Record<string, React.CSSProperties> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadHighlighter = async () => {
      try {
        const [{ Prism }, { oneDark }] = await Promise.all([
          import('react-syntax-highlighter'),
          import('react-syntax-highlighter/dist/esm/styles/prism'),
        ]);
        if (!cancelled) {
          setHighlighter(() => Prism);
          setStyle(oneDark as unknown as Record<string, React.CSSProperties>);
        }
      } catch {
        // Fallback: highlighter unavailable
      }
    };

    loadHighlighter();
    return () => { cancelled = true; };
  }, []);

  if (!Highlighter || !style) {
    return (
      <pre className="bg-muted rounded p-3 overflow-x-auto">
        <code className="text-sm font-mono text-foreground">{children}</code>
      </pre>
    );
  }

  return (
    <Highlighter style={style} language={language || 'text'} PreTag="div">
      {children}
    </Highlighter>
  );
}

/**
 * Parse content into collapsible sections based on markdown headers.
 * Pattern: ## Header followed by content until the next ## header.
 * Also captures any content BEFORE the first ## header as "preamble".
 *
 * Example:
 *   ```mermaid
 *   flowchart TD...
 *   ```
 *
 *   ## Summary
 *   This is the summary content...
 *
 *   ## Details
 *   These are the details...
 */
function parseHeaderDashSections(content: string): {
  preamble: string | null;
  sections: Array<{ title: string; content: string }>;
} | null {
  // Normalize line endings to \n
  const normalizedContent = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  // Pattern: ## Header (with optional trailing text)
  // Only match ## headers (not # or ###)
  const headerPattern = /^##\s+(.+?)(?:\n|$)/gm;

  const matches = [...normalizedContent.matchAll(headerPattern)];

  if (matches.length === 0) {
    return null;
  }

  const sections: Array<{ title: string; content: string }> = [];

  // Capture preamble (content before first ## header)
  const firstMatch = matches[0];
  const preamble = firstMatch.index! > 0
    ? normalizedContent.slice(0, firstMatch.index!).trim()
    : null;

  matches.forEach((match, idx) => {
    const title = match[1].trim();
    const contentStart = match.index! + match[0].length;

    // Content ends at the next ## header or end of content
    const nextMatch = matches[idx + 1];
    const contentEnd = nextMatch ? nextMatch.index! : normalizedContent.length;

    const sectionContent = normalizedContent.slice(contentStart, contentEnd).trim();

    if (sectionContent) {
      sections.push({ title, content: sectionContent });
    }
  });

  return sections.length > 0 ? { preamble, sections } : null;
}

export function MarkdownRenderer({
  content,
  enableMermaid = true,
  enableCodeHighlight = true,
  className = '',
}: MarkdownRendererProps) {
  // Parse content for header + dash sections
  const sections = useMemo(() => parseHeaderDashSections(content), [content]);

  const buildCodeComponent = useCallback((): Components['code'] => {
    return function CodeRenderer({ className: codeClassName, children, ...props }) {
      const match = /language-(\w+)/.exec(codeClassName || '');
      const language = match ? match[1] : '';
      const codeString = String(children).replace(/\n$/, '');
      const isInline = !codeClassName;

      // Mermaid code fence
      if (language === 'mermaid' && enableMermaid) {
        return <MermaidDiagram chart={codeString} />;
      }

      // Inline code
      if (isInline) {
        return (
          <code
            className="px-1.5 py-0.5 rounded bg-muted text-foreground font-mono text-sm"
            {...props}
          >
            {children}
          </code>
        );
      }

      // Fenced code block with syntax highlighting
      if (enableCodeHighlight) {
        return <HighlightedCode language={language}>{codeString}</HighlightedCode>;
      }

      // Fallback: plain code block without highlighting
      return (
        <pre className="bg-muted rounded p-3 overflow-x-auto">
          <code className="text-sm font-mono text-foreground">{codeString}</code>
        </pre>
      );
    };
  }, [enableMermaid, enableCodeHighlight]);

  const components: Components = useMemo(() => ({
    code: buildCodeComponent(),
    a({ href, children, ...props }) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  }), [buildCodeComponent]);

  return (
    <>
      {/* Custom styles for better markdown rendering */}
      <style jsx global>{`
        .markdown-content {
          line-height: 1.75;
          font-size: 0.9375rem;
        }
        .markdown-content h1 {
          font-size: 1.5rem;
          font-weight: 700;
          margin-top: 1rem;
          margin-bottom: 1rem;
          color: hsl(var(--foreground));
        }
        .markdown-content h2 {
          font-size: 1.375rem;
          font-weight: 700;
          margin-top: 2rem;
          margin-bottom: 1rem;
          padding-bottom: 0.5rem;
          border-bottom: 2px solid hsl(var(--border));
          color: hsl(var(--foreground));
        }
        .markdown-content h3 {
          font-size: 1.125rem;
          font-weight: 600;
          margin-top: 1.5rem;
          margin-bottom: 0.75rem;
          color: hsl(var(--foreground));
        }
        .markdown-content h4 {
          font-size: 1rem;
          font-weight: 600;
          margin-top: 1.25rem;
          margin-bottom: 0.5rem;
        }
        .markdown-content p {
          margin-top: 0.75rem;
          margin-bottom: 0.75rem;
        }
        .markdown-content ul, .markdown-content ol {
          margin-top: 0.75rem;
          margin-bottom: 0.75rem;
          padding-left: 1.5rem;
        }
        .markdown-content li {
          margin-top: 0.375rem;
          margin-bottom: 0.375rem;
        }
        .markdown-content hr {
          border: none;
          border-top: 2px solid hsl(var(--border));
          margin-top: 1.5rem;
          margin-bottom: 1.5rem;
          opacity: 1;
        }
        .markdown-content pre {
          margin-top: 1rem;
          margin-bottom: 1rem;
        }
        .markdown-content blockquote {
          border-left: 3px solid hsl(var(--primary));
          padding-left: 1rem;
          margin: 1rem 0;
          color: hsl(var(--muted-foreground));
        }
      `}</style>

      {sections && sections.sections.length > 0 ? (
        // Render preamble + collapsible sections (## header pattern detected)
        <div className={`space-y-4 ${className}`}>
          {/* Render preamble content — only if it contains a code block (e.g., mermaid
              diagrams). Plain-text preambles are spurious LLM output that should not
              appear as a large unstyled block above the structured sections. */}
          {sections.preamble && /```/.test(sections.preamble) && (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
                {sections.preamble}
              </ReactMarkdown>
            </div>
          )}

          {/* Render collapsible sections */}
          <div className="space-y-2">
            {sections.sections.map((section, idx) => (
              <CollapsibleSection
                key={idx}
                title={section.title}
                defaultOpen={idx === 0}
              >
                <div className="markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
                    {section.content}
                  </ReactMarkdown>
                </div>
              </CollapsibleSection>
            ))}
          </div>
        </div>
      ) : (
        // Standard markdown rendering (no ## header pattern)
        <div className={`markdown-content ${className}`}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {content}
          </ReactMarkdown>
        </div>
      )}
    </>
  );
}

/**
 * ProseContent - A unified wrapper for markdown content with consistent styling.
 * Use this instead of manually wrapping MarkdownRenderer with prose classes.
 *
 * This eliminates the repeated pattern of:
 *   <div className="prose prose-sm dark:prose-invert max-w-none">
 *     <MarkdownRenderer ... />
 *   </div>
 */
export function ProseContent({
  content,
  enableMermaid = false,
  enableCodeHighlight = true,
  className = '',
}: MarkdownRendererProps) {
  return (
    <div className={`prose prose-sm dark:prose-invert max-w-none ${className}`}>
      <MarkdownRenderer
        content={content}
        enableMermaid={enableMermaid}
        enableCodeHighlight={enableCodeHighlight}
      />
    </div>
  );
}
