'use client';

import { ScrollArea } from '@/components/ui/scroll-area';
import { ResearchContextCard } from './ResearchContextCard';
import { KnowledgeGapCard } from '@/components/review/KnowledgeGapCard';
import { RiskCard } from './RiskCard';
import type { ResearchContextCard as ContextCard, ResearchGap, ResearchRisk } from '@/lib/types/research';

interface TabContentWrapperProps {
  children: React.ReactNode;
  emptyMessage: string;
  hasItems: boolean;
}

/**
 * Shared wrapper for tab content with consistent scroll area and empty state.
 */
export function TabContentWrapper({ children, emptyMessage, hasItems }: TabContentWrapperProps) {
  return (
    <ScrollArea className="h-[500px] pr-4">
      <div className="space-y-4 py-4">
        {children}
        {!hasItems && (
          <div className="text-center py-8 text-muted-foreground text-sm">
            {emptyMessage}
          </div>
        )}
      </div>
    </ScrollArea>
  );
}

interface ContextTabContentProps {
  cards: ContextCard[];
}

export function ContextTabContent({ cards }: ContextTabContentProps) {
  return (
    <TabContentWrapper emptyMessage="No context cards collected yet" hasItems={cards.length > 0}>
      {cards.map((card) => (
        <ResearchContextCard key={card.id} card={card} />
      ))}
    </TabContentWrapper>
  );
}

interface GapsTabContentProps {
  gaps: ResearchGap[];
  onAnswer: (gapId: string, answer: string) => void;
}

export function GapsTabContent({ gaps, onAnswer }: GapsTabContentProps) {
  const mapGapToKnowledgeGap = (gap: ResearchGap) => ({
    id: gap.id,
    category: gap.category ?? 'scope',
    title: gap.question ?? '',
    description: gap.context ?? '',
    impact: gap.impact ?? 'medium',
    questions: [],
    suggestedAnswers: gap.suggestedAnswers ?? [],
  });

  return (
    <TabContentWrapper emptyMessage="No knowledge gaps detected" hasItems={gaps.length > 0}>
      {gaps.map((gap) => (
        <KnowledgeGapCard
          key={gap.id}
          gap={mapGapToKnowledgeGap(gap)}
          onAnswer={(gapId, _questionIndex, answer) => onAnswer(gapId, answer)}
        />
      ))}
    </TabContentWrapper>
  );
}

interface RisksTabContentProps {
  risks: ResearchRisk[] | undefined;
}

export function RisksTabContent({ risks }: RisksTabContentProps) {
  const hasRisks = Boolean(risks && risks.length > 0);

  return (
    <TabContentWrapper emptyMessage="No risks identified" hasItems={hasRisks}>
      {risks?.map((risk) => <RiskCard key={risk.id} risk={risk} />)}
    </TabContentWrapper>
  );
}
