'use client';

import React, { useMemo } from 'react';
import { MarkdownRenderer } from './MarkdownRenderer';
import { DocumentSuiteIndex } from './DocumentSuiteIndex';
import { CollapsibleSection } from '@/components/ui/collapsible';
import { CheckCircle, AlertTriangle, Info, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * StructuredContent — DRY component for rendering LLM output across the app.
 *
 * Handles:
 *  - Raw markdown strings → MarkdownRenderer (with collapsible ## sections)
 *  - JSON task results → collapsible task cards
 *  - Mixed content → auto-detects and renders appropriately
 *
 * Used by: WizardPanelMessage (phase results), Message (ask responses),
 *          and any future LLM output rendering.
 */

interface StructuredContentProps {
    /** The content to render — markdown string, JSON string, or structured data */
    content: string | Record<string, unknown> | unknown[];
    /** Optional title shown above the content */
    title?: string;
    /** Visual variant */
    variant?: 'default' | 'green' | 'blue' | 'amber';
    /** Max height before scrolling (CSS value) */
    maxHeight?: string;
    /** Whether to start sections collapsed */
    defaultCollapsed?: boolean;
    /** Additional CSS classes */
    className?: string;
}

interface TaskResult {
    task_id?: string;
    title?: string;
    output?: string;
    confidence_score?: number;
    iteration?: number;
}

function deriveArrayItemTitle(item: unknown, idx: number): string {
    if (typeof item === 'string') {
        const trimmed = item.trim();
        if (trimmed && trimmed.length <= 80) {
            return trimmed;
        }
        return `Item ${idx + 1}`;
    }

    if (!item || typeof item !== 'object') {
        return `Item ${idx + 1}`;
    }

    const candidate = item as Record<string, unknown>;
    const titleKeys = [
        'title',
        'heading',
        'filename',
        'name',
        'label',
        'specSection',
        'task_id',
        'id',
        'key',
        'url',
    ];

    for (const key of titleKeys) {
        const value = candidate[key];
        if (typeof value === 'string' && value.trim()) {
            return value.trim();
        }
    }

    return `Item ${idx + 1}`;
}

/** Pattern for orchestration task entries: ✓ TaskName (iterations: N, confidence: P%) */
const ORCHESTRATION_TASK_PATTERN = /^[\s]*[✓✅]?\s*(.+?)\s*\(iterations:\s*(\d+),\s*confidence:\s*(\d+)%?\)/;
const ORCHESTRATION_HEADER_PATTERN = /^⚙️\s*Orchestration:\s*(\d+)\/(\d+)\s*tasks?\s*completed/i;

/** Parse orchestration summary text into structured task results */
function parseOrchestrationSummary(content: string): { tasks: TaskResult[]; completed: number; total: number } | null {
    const lines = content.trim().split('\n');
    if (lines.length === 0) return null;

    // Check for header pattern
    const headerMatch = lines[0].match(ORCHESTRATION_HEADER_PATTERN);
    if (!headerMatch) return null;

    const completed = parseInt(headerMatch[1], 10);
    const total = parseInt(headerMatch[2], 10);
    const tasks: TaskResult[] = [];

    // Parse task lines
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i];
        const taskMatch = line.match(ORCHESTRATION_TASK_PATTERN);
        if (taskMatch) {
            tasks.push({
                task_id: `task-${i}`,
                title: taskMatch[1].trim(),
                iteration: parseInt(taskMatch[2], 10),
                confidence_score: parseInt(taskMatch[3], 10) / 100,
                output: undefined, // Will be expanded to show details
            });
        }
    }

    return tasks.length > 0 ? { tasks, completed, total } : null;
}

const variantMap = {
    default: 'default' as const,
    green: 'emerald' as const,
    blue: 'sky' as const,
    amber: 'amber' as const,
};


/** Try to parse a JSON string into task results array */
function parseTaskResults(content: string): TaskResult[] | null {
    try {
        const parsed = JSON.parse(content);
        if (Array.isArray(parsed)) {
            return parsed.filter(
                (item) => item && typeof item === 'object' && (item.output || item.title || item.task_id)
            );
        }
        // Single object with task_results array
        if (parsed?.task_results && Array.isArray(parsed.task_results)) {
            return parsed.task_results;
        }
        return null;
    } catch {
        return null;
    }
}

/** Detect if content looks like structured JSON (task results, etc.) or orchestration summary */
function detectContentType(content: string): 'document_index' | 'tasks' | 'orchestration' | 'json' | 'markdown' {
    const trimmed = content.trim();

    if (/^#\s+Document Suite Index:/im.test(trimmed) && /^##\s+Table of Contents/im.test(trimmed)) {
        return 'document_index';
    }

    // Check for orchestration summary pattern first (markdown-based)
    if (ORCHESTRATION_HEADER_PATTERN.test(trimmed)) {
        return 'orchestration';
    }

    if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
        const tasks = parseTaskResults(trimmed);
        if (tasks && tasks.length > 0) return 'tasks';
        try {
            JSON.parse(trimmed);
            return 'json';
        } catch {
            // Not valid JSON, treat as markdown
        }
    }
    return 'markdown';
}

/** Render a confidence score as a colored badge */
function ConfidenceBadge({ score }: { score: number }) {
    const pct = Math.round(score * 100);
    return (
        <span className={cn(
            'text-xs font-medium px-2 py-0.5 rounded-full',
            pct >= 80 ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                : pct >= 50 ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                    : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
        )}>
            {pct}%
        </span>
    );
}

function ValueContent({
    value,
    defaultCollapsed,
    sectionVariant,
}: {
    value: unknown;
    defaultCollapsed: boolean;
    sectionVariant: 'default' | 'emerald' | 'sky' | 'amber' | 'violet';
}) {
    if (Array.isArray(value)) {
        return (
            <ArrayContent
                items={value}
                defaultCollapsed={defaultCollapsed}
                sectionVariant={sectionVariant}
            />
        );
    }

    if (value && typeof value === 'object') {
        return (
            <JsonContent
                data={value as Record<string, unknown>}
                defaultCollapsed={defaultCollapsed}
                sectionVariant={sectionVariant}
            />
        );
    }

    const content = typeof value === 'string'
        ? value
        : typeof value === 'number' || typeof value === 'boolean'
            ? String(value)
            : 'No content available';

    if (typeof value === 'string' && value.length > 50) {
        return <MarkdownRenderer content={content} enableMermaid={false} />;
    }

    return (
        <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono bg-gray-50 dark:bg-gray-900 rounded p-2 overflow-x-auto">
            {content}
        </pre>
    );
}

/** Render task results as collapsible cards */
function TaskResultCards({
    tasks,
    defaultCollapsed,
    sectionVariant,
}: {
    tasks: TaskResult[];
    defaultCollapsed: boolean;
    sectionVariant: 'default' | 'emerald' | 'sky' | 'amber' | 'violet';
}) {
    return (
        <div className="space-y-2">
            {tasks.map((task, idx) => {
                const title = task.title || task.task_id || `Task ${idx + 1}`;
                const hasOutput = !!task.output;
                return (
                    <CollapsibleSection
                        key={task.task_id || idx}
                        title={title}
                        defaultOpen={!defaultCollapsed && idx === 0}
                        variant={sectionVariant}
                        size="sm"
                        icon={<FileText className="w-3.5 h-3.5" />}
                        badge={
                            <span className="flex items-center gap-2">
                                {task.confidence_score != null && (
                                    <ConfidenceBadge score={task.confidence_score} />
                                )}
                                {task.iteration != null && task.iteration > 1 && (
                                    <span className="text-xs text-gray-500">iter {task.iteration}</span>
                                )}
                            </span>
                        }
                    >
                        {hasOutput ? (
                            <MarkdownRenderer content={task.output!} enableMermaid={false} />
                        ) : (
                            <p className="text-sm text-gray-500 italic">No output</p>
                        )}
                    </CollapsibleSection>
                );
            })}
        </div>
    );
}


/** Render a JSON object as collapsible key-value sections */
function JsonContent({
    data,
    defaultCollapsed,
    sectionVariant,
}: {
    data: Record<string, unknown>;
    defaultCollapsed: boolean;
    sectionVariant: 'default' | 'emerald' | 'sky' | 'amber' | 'violet';
}) {
    const entries = Object.entries(data).filter(([, v]) => v != null && v !== '');
    return (
        <div className="space-y-2">
            {entries.map(([key, value], idx) => {
                const title = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
                return (
                    <CollapsibleSection
                        key={key}
                        title={title}
                        defaultOpen={!defaultCollapsed && idx < 2}
                        variant={sectionVariant}
                        size="sm"
                    >
                        <ValueContent
                            value={value}
                            defaultCollapsed={true}
                            sectionVariant={sectionVariant}
                        />
                    </CollapsibleSection>
                );
            })}
        </div>
    );
}

function ArrayContent({
    items,
    defaultCollapsed,
    sectionVariant,
}: {
    items: unknown[];
    defaultCollapsed: boolean;
    sectionVariant: 'default' | 'emerald' | 'sky' | 'amber' | 'violet';
}) {
    if (items.length === 0) {
        return <p className="text-sm text-gray-500 italic">No items</p>;
    }

    return (
        <div className="space-y-2">
            {items.map((item, idx) => (
                <CollapsibleSection
                    key={`${deriveArrayItemTitle(item, idx)}-${idx}`}
                    title={deriveArrayItemTitle(item, idx)}
                    defaultOpen={!defaultCollapsed && idx === 0}
                    variant={sectionVariant}
                    size="sm"
                    icon={<FileText className="w-3.5 h-3.5" />}
                >
                    <ValueContent
                        value={item}
                        defaultCollapsed={true}
                        sectionVariant={sectionVariant}
                    />
                </CollapsibleSection>
            ))}
        </div>
    );
}

export function StructuredContent({
    content,
    title,
    variant = 'default',
    maxHeight = '600px',
    defaultCollapsed = false,
    className,
}: StructuredContentProps) {
    const sectionVariant = variantMap[variant];

    const rendered = useMemo(() => {
        // Handle object input directly
        if (typeof content === 'object' && content !== null) {
            // Check for task_results array
            if (Array.isArray((content as Record<string, unknown>).task_results)) {
                return {
                    type: 'tasks' as const,
                    tasks: (content as Record<string, unknown>).task_results as TaskResult[],
                };
            }
            if (Array.isArray(content)) {
                return { type: 'array' as const, items: content };
            }
            return { type: 'json' as const, data: content as Record<string, unknown> };
        }

        // String content
        const str = String(content);
        const contentType = detectContentType(str);

        if (contentType === 'document_index') {
            return { type: 'document_index' as const, text: str };
        }
        if (contentType === 'orchestration') {
            const parsed = parseOrchestrationSummary(str);
            if (parsed) {
                return { type: 'orchestration' as const, ...parsed };
            }
        }
        if (contentType === 'tasks') {
            return { type: 'tasks' as const, tasks: parseTaskResults(str)! };
        }
        if (contentType === 'json') {
            try {
                const parsed = JSON.parse(str) as unknown;
                if (Array.isArray(parsed)) {
                    return { type: 'array' as const, items: parsed };
                }
                return { type: 'json' as const, data: parsed as Record<string, unknown> };
            } catch {
                return { type: 'markdown' as const, text: str };
            }
        }
        return { type: 'markdown' as const, text: str };
    }, [content]);

    return (
        <div className={cn('overflow-y-auto', className)} style={{ maxHeight }}>
            {title && (
                <div className="flex items-center gap-2 mb-3">
                    {variant === 'green' && <CheckCircle className="w-4 h-4 text-green-500" />}
                    {variant === 'amber' && <AlertTriangle className="w-4 h-4 text-amber-500" />}
                    {variant === 'blue' && <Info className="w-4 h-4 text-blue-500" />}
                    <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                        {title}
                    </span>
                </div>
            )}

            {rendered.type === 'tasks' && (
                <TaskResultCards
                    tasks={rendered.tasks}
                    defaultCollapsed={defaultCollapsed}
                    sectionVariant={sectionVariant}
                />
            )}

            {rendered.type === 'orchestration' && (
                <div className="space-y-3">
                    {/* Summary header */}
                    <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg">
                        <CheckCircle className="w-4 h-4 text-emerald-500" />
                        <span className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
                            {rendered.completed} of {rendered.total} tasks completed
                        </span>
                    </div>
                    {/* Task cards */}
                    <TaskResultCards
                        tasks={rendered.tasks}
                        defaultCollapsed={true}
                        sectionVariant="emerald"
                    />
                </div>
            )}

            {rendered.type === 'json' && (
                <JsonContent
                    data={rendered.data}
                    defaultCollapsed={defaultCollapsed}
                    sectionVariant={sectionVariant}
                />
            )}

            {rendered.type === 'array' && (
                <ArrayContent
                    items={rendered.items}
                    defaultCollapsed={defaultCollapsed}
                    sectionVariant={sectionVariant}
                />
            )}

            {rendered.type === 'markdown' && (
                <MarkdownRenderer content={rendered.text} enableMermaid={false} />
            )}

            {rendered.type === 'document_index' && (
                <DocumentSuiteIndex content={rendered.text} />
            )}
        </div>
    );
}

export default StructuredContent;
