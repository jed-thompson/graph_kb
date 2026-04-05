'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Sparkles, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';

interface LLMReviewTriggerProps {
  onTriggerReview: () => void;
}

/**
 * LLMReviewTrigger - Button to trigger LLM review of gathered context.
 * Displays review status and results when complete.
 */
export function LLMReviewTrigger({ onTriggerReview }: LLMReviewTriggerProps) {
  const { status, llmReviewStatus, llmReviewResult, setLlmReviewStatus } = useResearchStore();
  const [isExpanded, setIsExpanded] = useState(true);

  const canTriggerReview = status === 'complete' && llmReviewStatus === 'idle';
  const isReviewing = llmReviewStatus === 'running';
  const hasReview = llmReviewStatus === 'complete' && llmReviewResult;

  const getStatusBadge = () => {
    switch (llmReviewStatus) {
      case 'running':
        return (
          <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
            <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            Reviewing...
          </Badge>
        );
      case 'complete':
        return (
          <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
            <CheckCircle className="h-3 w-3 mr-1" />
            Complete
          </Badge>
        );
      case 'error':
        return (
          <Badge variant="destructive">
            <AlertCircle className="h-3 w-3 mr-1" />
            Error
          </Badge>
        );
      default:
        return (
          <Badge variant="secondary">
            Not Started
          </Badge>
        );
    }
  };

  const getAssessmentColor = (assessment: string) => {
    switch (assessment) {
      case 'excellent':
        return 'text-green-500';
      case 'good':
        return 'text-blue-500';
      case 'adequate':
        return 'text-amber-500';
      case 'needs_improvement':
        return 'text-red-500';
      default:
        return 'text-muted-foreground';
    }
  };

  return (
    <Card className="overflow-hidden">
      <div className="p-4 border-b bg-muted/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          <h3 className="font-semibold">LLM Context Review</h3>
        </div>
        {getStatusBadge()}
      </div>

      <CardContent className="p-4 space-y-4">
        {/* Trigger Button */}
        {canTriggerReview && (
          <div className="text-center py-4">
            <p className="text-sm text-muted-foreground mb-4">
              Have an LLM review your gathered context for quality, completeness, and relevance.
            </p>
            <Button onClick={onTriggerReview} size="lg" className="gap-2">
              <Sparkles className="h-4 w-4" />
              Start LLM Review
            </Button>
          </div>
        )}

        {/* Reviewing State */}
        {isReviewing && (
          <div className="text-center py-8">
            <Loader2 className="h-8 w-8 mx-auto text-primary animate-spin mb-3" />
            <p className="font-medium">Reviewing your research context...</p>
            <p className="text-sm text-muted-foreground mt-1">
              This may take a moment while the LLM analyzes your gathered context.
            </p>
          </div>
        )}

        {/* Review Results */}
        {hasReview && llmReviewResult && (
          <div className="space-y-4">
            {/* Overall Assessment */}
            <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
              <span className="text-sm font-medium">Overall Assessment</span>
              <span className={`font-semibold capitalize ${getAssessmentColor(llmReviewResult.overallAssessment)}`}>
                {llmReviewResult.overallAssessment.replace('_', ' ')}
              </span>
            </div>

            {/* Summary */}
            <div>
              <p className="text-sm font-medium mb-2">Summary</p>
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <MarkdownRenderer content={llmReviewResult.summary} />
              </div>
            </div>

            {/* Strengths */}
            {llmReviewResult.strengths.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-2 text-green-500">Strengths</p>
                <ul className="text-sm space-y-1">
                  {llmReviewResult.strengths.map((strength, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <CheckCircle className="h-4 w-4 text-green-500 shrink-0 mt-0.5" />
                      {strength}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Weaknesses */}
            {llmReviewResult.weaknesses.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-2 text-amber-500">Areas for Improvement</p>
                <ul className="text-sm space-y-1">
                  {llmReviewResult.weaknesses.map((weakness, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                      {weakness}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommendations */}
            {llmReviewResult.recommendations.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-2 text-blue-500">Recommendations</p>
                <ul className="text-sm space-y-1">
                  {llmReviewResult.recommendations.map((rec, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <Sparkles className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                      {rec}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Waiting State */}
        {status !== 'complete' && llmReviewStatus === 'idle' && (
          <div className="text-center py-4 text-muted-foreground text-sm">
            <p>Complete research first to enable LLM review</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default LLMReviewTrigger;
