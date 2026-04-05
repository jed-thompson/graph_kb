'use client';

import React, { useMemo } from 'react';
import { BookOpenText, CheckCircle2, FileStack, GitBranch, Hash } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { MarkdownRenderer } from './MarkdownRenderer';

interface DocumentSuiteIndexProps {
  content: string;
}

interface TocEntry {
  status: string;
  title: string;
  sectionKey: string;
  tokens: number;
}

interface ParsedDocumentSuiteIndex {
  suiteName: string;
  totalDocuments: number | null;
  totalTokens: number | null;
  entries: TocEntry[];
  crossReferenceText: string;
}

const numberFormatter = new Intl.NumberFormat('en-US');

function extractSection(content: string, sectionTitle: string): string {
  const escapedTitle = sectionTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`^##\\s+${escapedTitle}\\s*$([\\s\\S]*?)(?=^##\\s+|\\Z)`, 'im');
  return content.match(pattern)?.[1]?.trim() ?? '';
}

function parseDocumentSuiteIndex(content: string): ParsedDocumentSuiteIndex | null {
  const suiteName = content.match(/^#\s+Document Suite Index:\s*(.+)$/m)?.[1]?.trim();
  if (!suiteName || !content.includes('## Table of Contents')) {
    return null;
  }

  const totalDocuments = content.match(/\*\*Total Documents:\*\*\s*(\d+)/i)?.[1];
  const totalTokens = content.match(/\*\*Total Tokens:\*\*\s*(\d+)/i)?.[1];
  const tocBlock = extractSection(content, 'Table of Contents');
  const crossReferenceText = extractSection(content, 'Cross-Reference Map');

  const entries = tocBlock
    .split('\n')
    .map((line) => line.trim())
    .map((line) => {
      const match = line.match(/^- \[([^\]]+)\]\s+\*\*(.+?)\*\*\s+\(`([^`]+)`\)\s+(?:—|â|-)\s+(\d+)\s+tokens$/i);
      if (!match) {
        return null;
      }
      return {
        status: match[1].trim(),
        title: match[2].trim(),
        sectionKey: match[3].trim(),
        tokens: Number(match[4]),
      } satisfies TocEntry;
    })
    .filter((entry): entry is TocEntry => entry !== null);

  return {
    suiteName,
    totalDocuments: totalDocuments ? Number(totalDocuments) : null,
    totalTokens: totalTokens ? Number(totalTokens) : null,
    entries,
    crossReferenceText,
  };
}

function formatTokenCount(tokens: number): string {
  return `${numberFormatter.format(tokens)} tokens`;
}

export function DocumentSuiteIndex({ content }: DocumentSuiteIndexProps) {
  const parsed = useMemo(() => parseDocumentSuiteIndex(content), [content]);

  if (!parsed) {
    return <MarkdownRenderer content={content} enableMermaid={false} />;
  }

  const hasDependencies = parsed.crossReferenceText
    && !/^no inter-document dependencies detected\.?$/i.test(parsed.crossReferenceText.trim());

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/60">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-blue-50 p-2 text-blue-600 dark:bg-blue-950/40 dark:text-blue-300">
            <BookOpenText className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
              Document Suite Index
            </p>
            <h3 className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {parsed.suiteName}
            </h3>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
            <FileStack className="h-4 w-4" />
            <span className="text-xs font-medium uppercase tracking-wide">Documents</span>
          </div>
          <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            {parsed.totalDocuments ?? parsed.entries.length}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
            <Hash className="h-4 w-4" />
            <span className="text-xs font-medium uppercase tracking-wide">Total Tokens</span>
          </div>
          <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            {parsed.totalTokens != null ? numberFormatter.format(parsed.totalTokens) : '—'}
          </div>
        </div>
      </div>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <BookOpenText className="h-4 w-4 text-slate-500 dark:text-slate-400" />
          <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Table of Contents</h4>
        </div>
        <div className="space-y-2">
          {parsed.entries.map((entry, index) => (
            <div
              key={`${entry.sectionKey}-${index}`}
              className="grid grid-cols-[auto,1fr,auto] items-start gap-3 rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/50"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {index + 1}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="gap-1 border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                    <CheckCircle2 className="h-3 w-3" />
                    {entry.status}
                  </Badge>
                  <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {entry.title}
                  </span>
                </div>
                <div className="mt-1 break-all font-mono text-xs text-slate-500 dark:text-slate-400">
                  {entry.sectionKey}
                </div>
              </div>
              <div className="whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {formatTokenCount(entry.tokens)}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-slate-500 dark:text-slate-400" />
          <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Cross-Reference Map</h4>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/50">
          {hasDependencies ? (
            <MarkdownRenderer content={parsed.crossReferenceText} enableMermaid={false} />
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No inter-document dependencies detected.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

export default DocumentSuiteIndex;
