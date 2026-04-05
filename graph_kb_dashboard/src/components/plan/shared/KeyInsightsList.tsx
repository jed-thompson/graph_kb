'use client';

import { cleanAIText } from '@/lib/utils/cleanAIText';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { Lightbulb } from 'lucide-react';
import { extractDisplayText } from './extractDisplayText';

interface KeyInsightsListProps {
    insights: unknown;
}

export function KeyInsightsList({ insights }: KeyInsightsListProps) {
    if (!insights || !Array.isArray(insights) || insights.length === 0) return null;

    return (
        <div className="mt-4 pt-4 border-t">
            <p className="text-sm font-medium mb-2">Key Insights:</p>
            <ul className="space-y-1.5">
                {insights.map((insight, i) => {
                    const text = cleanAIText(extractDisplayText(insight));
                    return (
                        <li key={i} className="flex items-start gap-2">
                            <Lightbulb className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
                            <div className="min-w-0 flex-1 text-sm text-muted-foreground">
                                <MarkdownRenderer content={text} />
                            </div>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}
