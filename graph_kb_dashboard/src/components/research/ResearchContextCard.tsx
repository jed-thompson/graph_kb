'use client';

import { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import {
  Globe,
  FileText,
  GitBranch,
  Sparkles,
  ChevronDown,
  ThumbsUp,
  ThumbsDown,
  MessageSquare,
  ExternalLink,
} from 'lucide-react';
import type { ResearchContextCard as ContextCardType } from '@/lib/types/research';
import { cn } from '@/lib/utils';

interface ResearchContextCardProps {
  card: ContextCardType;
  onAddFeedback?: (cardId: string, comment: string, rating: 'helpful' | 'not_helpful' | 'needs_revision') => void;
}

const SOURCE_ICONS = {
  web: Globe,
  document: FileText,
  repository: GitBranch,
  generated: Sparkles,
};

const SOURCE_COLORS = {
  web: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
  document: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  repository: 'bg-green-500/10 text-green-500 border-green-500/20',
  generated: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
};

/**
 * ResearchContextCard - Individual context card with mermaid support.
 * Uses MarkdownRenderer for content with possible mermaid diagrams.
 */
export function ResearchContextCard({ card, onAddFeedback }: ResearchContextCardProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackComment, setFeedbackComment] = useState('');

  const SourceIcon = SOURCE_ICONS[card.sourceType];
  const sourceColor = SOURCE_COLORS[card.sourceType];

  const handleRating = (rating: 'helpful' | 'not_helpful' | 'needs_revision') => {
    if (onAddFeedback && feedbackComment.trim()) {
      onAddFeedback(card.id, feedbackComment, rating);
      setFeedbackComment('');
      setShowFeedback(false);
    }
  };

  const formatRelevanceScore = (score: number) => {
    return `${Math.round(score * 100)}% relevant`;
  };

  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <Card className="overflow-hidden">
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer hover:bg-muted/50 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <div className={cn('p-2 rounded-lg border', sourceColor)}>
                  <SourceIcon className="h-4 w-4" />
                </div>
                <div className="space-y-1">
                  <CardTitle className="text-base leading-tight">{card.title}</CardTitle>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span>{card.sourceName}</span>
                    {card.sourceUrl && (
                      <a
                        href={card.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="hover:text-primary"
                      >
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant="outline" className="text-xs">
                  {formatRelevanceScore(card.relevanceScore)}
                </Badge>
                <ChevronDown
                  className={cn(
                    'h-5 w-5 text-muted-foreground transition-transform',
                    isExpanded && 'rotate-180'
                  )}
                />
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0 space-y-4">
            {/* Tags */}
            {(card.tags?.length ?? 0) > 0 && (
              <div className="flex flex-wrap gap-1">
                {(card.tags ?? []).map((tag) => (
                  <Badge key={tag} variant="secondary" className="text-xs">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}

            {/* Content with Mermaid Support */}
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <MarkdownRenderer content={card.content} />
            </div>

            {/* Existing Feedback */}
            {card.feedback && (
              <div className="bg-muted/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <MessageSquare className="h-4 w-4" />
                  Feedback
                </div>
                <p className="text-sm text-muted-foreground">{card.feedback.comment}</p>
                <Badge
                  variant={
                    card.feedback.rating === 'helpful'
                      ? 'default'
                      : card.feedback.rating === 'not_helpful'
                        ? 'destructive'
                        : 'secondary'
                  }
                  className="text-xs"
                >
                  {card.feedback.rating.replace('_', ' ')}
                </Badge>
              </div>
            )}

            {/* Feedback Input */}
            {showFeedback && (
              <div className="space-y-3 pt-3 border-t">
                <Textarea
                  placeholder="Add your feedback about this context..."
                  value={feedbackComment}
                  onChange={(e) => setFeedbackComment(e.target.value)}
                  rows={3}
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleRating('helpful')}
                    disabled={!feedbackComment.trim()}
                  >
                    <ThumbsUp className="h-3 w-3 mr-1" />
                    Helpful
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleRating('needs_revision')}
                    disabled={!feedbackComment.trim()}
                  >
                    Needs Revision
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleRating('not_helpful')}
                    disabled={!feedbackComment.trim()}
                  >
                    <ThumbsDown className="h-3 w-3 mr-1" />
                    Not Helpful
                  </Button>
                </div>
              </div>
            )}

            {/* Add Feedback Button */}
            {!card.feedback && !showFeedback && onAddFeedback && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowFeedback(true)}
                className="text-muted-foreground"
              >
                <MessageSquare className="h-3 w-3 mr-1" />
                Add Feedback
              </Button>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}

export default ResearchContextCard;
