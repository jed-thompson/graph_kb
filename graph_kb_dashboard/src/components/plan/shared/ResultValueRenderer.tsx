'use client';

import { Badge } from '@/components/ui/badge';
import { CollapsibleSection } from '@/components/ui/collapsible';
import { AlertTriangle, Info, AlertCircle, BookOpen, Lightbulb, Ban, RotateCcw } from 'lucide-react';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { ArchitectureFeedbackItem, type ItemFeedback } from './ArchitectureFeedbackItem';
import { extractDisplayText } from './extractDisplayText';

interface ResultValueRendererProps {
    keyName: string;
    value: unknown;
    onGapFeedback?: (gapId: string, feedback: ItemFeedback) => void;
    gapFeedbackValues?: Record<string, ItemFeedback>;
    onGapDismiss?: (gapId: string) => void;
    dismissedGapIds?: Set<string>;
}

/** Smart renderer for approval/review summary values. */
export function ResultValueRenderer({ keyName, value, onGapFeedback, gapFeedbackValues, onGapDismiss, dismissedGapIds }: ResultValueRendererProps) {
    // --- Gaps array (all_gaps / top_gaps / gaps) ---
    if ((keyName === 'all_gaps' || keyName === 'top_gaps' || keyName === 'gaps') && Array.isArray(value)) {
        if (value.length === 0) {
            return <span className="text-muted-foreground italic text-xs">None</span>;
        }
        const gaps = value as Record<string, string>[];
        const hasFeedback = !!onGapFeedback;
        const gapItems = gaps.map((gap, i) => {
            const gapId = gap.id || gap.gap_id || `gap_${i}`;
            const isDismissed = dismissedGapIds?.has(gapId) ?? false;
            const importance = (gap.importance || gap.severity || 'medium').toLowerCase();
            const severityIcon = importance === 'high'
                ? <AlertTriangle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                : importance === 'low'
                    ? <Info className="h-3.5 w-3.5 text-blue-500 shrink-0 mt-0.5" />
                    : <AlertCircle className="h-3.5 w-3.5 text-yellow-500 shrink-0 mt-0.5" />;
            const severityVariant = importance === 'high'
                ? 'destructive' as const
                : importance === 'low'
                    ? 'secondary' as const
                    : 'default' as const;
            const question = cleanAIText(gap.question || gap.description || 'Unknown gap');

            if (hasFeedback) {
                return (
                    <ArchitectureFeedbackItem
                        key={gapId}
                        itemId={gapId}
                        label={question}
                        description={gap.context || gap.title || undefined}
                        value={gapFeedbackValues?.[gapId]}
                        onChange={onGapFeedback}
                        onDismiss={onGapDismiss}
                        dismissed={isDismissed}
                    >
                        <div className="flex items-center gap-2">
                            {severityIcon}
                            <span className="text-xs font-medium leading-tight">{question}</span>
                            <Badge variant={severityVariant} className="text-[10px] shrink-0">{importance}</Badge>
                        </div>
                    </ArchitectureFeedbackItem>
                );
            }

            return (
                <div key={gapId} className={`flex items-start gap-2 bg-background/80 px-2.5 py-2 rounded-md border ${isDismissed ? 'opacity-50' : ''}`}>
                    {severityIcon}
                    <div className="min-w-0 flex-1">
                        <p className={`text-xs font-medium leading-tight ${isDismissed ? 'line-through' : ''}`}>{question}</p>
                    </div>
                    {onGapDismiss && (
                        <button
                            type="button"
                            onClick={() => onGapDismiss(gapId)}
                            className={`shrink-0 ml-1 transition-opacity ${isDismissed ? 'text-muted-foreground hover:text-primary opacity-100' : 'text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100'}`}
                            aria-label={isDismissed ? 'Restore gap' : 'Dismiss gap'}
                        >
                            {isDismissed ? <RotateCcw className="h-3.5 w-3.5" /> : <Ban className="h-3.5 w-3.5" />}
                        </button>
                    )}
                    <Badge variant={severityVariant} className="text-[10px] shrink-0">{importance}</Badge>
                </div>
            );
        });
        const activeCount = value.length - (dismissedGapIds?.size ?? 0);
        return (
            <CollapsibleSection
                title={`${value.length} Gap${value.length !== 1 ? 's' : ''} Identified`}
                badge={<Badge variant={activeCount < value.length ? 'secondary' : 'destructive'} className="text-[10px]">{activeCount} active</Badge>}
                icon={<AlertTriangle className="h-4 w-4 text-destructive" />}
                defaultOpen={value.length <= 5}
                variant="default"
                size="sm"
                className="mt-1"
            >
                <div className="space-y-1.5">{gapItems}</div>
            </CollapsibleSection>
        );
    }

    // --- String arrays (key_insights, sources_used, etc.) ---
    if (Array.isArray(value)) {
        if (value.length === 0) {
            return <span className="text-muted-foreground italic text-xs">None</span>;
        }
        const isInsightKey = keyName.includes('insight');
        const isSourceKey = keyName.includes('source');
        const Icon = isInsightKey ? Lightbulb : isSourceKey ? BookOpen : null;

        return (
            <div className="space-y-1.5 mt-0.5">
                {value.map((item, i) => {
                    const text = cleanAIText(extractDisplayText(item));
                    return (
                        <div key={i} className="flex items-start gap-1.5">
                            {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />}
                            {!Icon && <span className="text-primary text-xs mt-0.5 shrink-0">&#8226;</span>}
                            {isInsightKey ? (
                                <div className="min-w-0 flex-1 text-xs leading-relaxed">
                                    <MarkdownRenderer content={text} />
                                </div>
                            ) : isSourceKey ? (
                                <Badge variant="outline" className="text-xs">{text}</Badge>
                            ) : (
                                <span className="text-xs leading-relaxed">{text}</span>
                            )}
                        </div>
                    );
                })}
            </div>
        );
    }

    // --- Confidence score ---
    if (keyName === 'confidence_score' && typeof value === 'number') {
        const pct = Math.round(value * 100);
        const color = pct >= 70 ? 'text-green-600' : pct >= 40 ? 'text-yellow-600' : 'text-red-500';
        return <span className={`font-semibold text-xs ${color}`}>{pct}%</span>;
    }

    // --- Plain objects ---
    if (typeof value === 'object' && value !== null) {
        const entries = Object.entries(value as Record<string, unknown>);
        if (entries.length === 0) return <span className="text-muted-foreground italic text-xs">None</span>;
        return (
            <div className="space-y-1 mt-0.5 text-xs">
                {entries.map(([k, v]) => (
                    <div key={k} className="flex gap-2">
                        <span className="text-muted-foreground capitalize">{k.replace(/_/g, ' ')}:</span>
                        <span>{cleanAIText(typeof v === 'object' ? JSON.stringify(v) : String(v))}</span>
                    </div>
                ))}
            </div>
        );
    }

    // --- Primitive fallback ---
    return <span>{cleanAIText(String(value))}</span>;
}
