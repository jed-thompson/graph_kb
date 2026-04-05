'use client';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Sparkles } from 'lucide-react';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import type { ResearchFindings } from '@/lib/types/research';

interface ResearchFindingsSummaryProps {
  findings: ResearchFindings;
}

/**
 * Displays research findings summary with confidence score and key insights.
 */
export function ResearchFindingsSummary({ findings }: ResearchFindingsSummaryProps) {
  return (
    <Card className="p-6">
      <div className="flex items-center gap-2 mb-4">
        <Sparkles className="h-5 w-5 text-primary" />
        <h3 className="font-semibold">Research Findings</h3>
        <Badge variant="outline" className="ml-auto">
          {Math.round(findings.confidenceScore * 100)}% Confidence
        </Badge>
      </div>
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <MarkdownRenderer content={findings.summary} />
      </div>
      {findings.keyInsights.length > 0 && (
        <KeyInsightsList insights={findings.keyInsights} />
      )}
    </Card>
  );
}

interface KeyInsightsListProps {
  insights: string[];
}

function KeyInsightsList({ insights }: KeyInsightsListProps) {
  return (
    <div className="mt-4 pt-4 border-t">
      <p className="text-sm font-medium mb-2">Key Insights:</p>
      <ul className="text-sm text-muted-foreground space-y-1">
        {insights.map((insight, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className="text-primary">•</span>
            {insight}
          </li>
        ))}
      </ul>
    </div>
  );
}
