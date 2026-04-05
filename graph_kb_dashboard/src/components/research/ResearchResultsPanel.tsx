'use client';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { FileText, AlertTriangle } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import { ResearchResultsEmptyState } from './ResearchResultsEmptyState';
import { ResearchFindingsSummary } from './ResearchFindingsSummary';
import { ContextTabContent, GapsTabContent, RisksTabContent } from './ResearchTabContent';

/**
 * ResearchResultsPanel - Container for research result cards.
 * Displays context cards, knowledge gaps, and findings in tabs.
 */
export function ResearchResultsPanel() {
  const { contextCards, gaps, findings, status, updateGapAnswer } = useResearchStore();

  const hasResults = contextCards.length > 0 || gaps.length > 0 || findings;
  const isComplete = status === 'complete';

  const handleGapAnswer = (gapId: string, answer: string) => {
    updateGapAnswer(gapId, answer);
  };

  if (!hasResults && !isComplete) {
    return <ResearchResultsEmptyState />;
  }

  return (
    <div className="space-y-4">
      {findings && <ResearchFindingsSummary findings={findings} />}

      <Tabs defaultValue="context" className="w-full">
        <TabsList className="w-full grid grid-cols-3">
          <TabsTrigger value="context" className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Context ({contextCards.length})
          </TabsTrigger>
          <TabsTrigger value="gaps" className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            Gaps ({gaps.length})
          </TabsTrigger>
          <TabsTrigger
            value="risks"
            className="flex items-center gap-2"
            disabled={!findings?.risks?.length}
          >
            Risks ({findings?.risks?.length || 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="context">
          <ContextTabContent cards={contextCards} />
        </TabsContent>

        <TabsContent value="gaps">
          <GapsTabContent gaps={gaps} onAnswer={handleGapAnswer} />
        </TabsContent>

        <TabsContent value="risks">
          <RisksTabContent risks={findings?.risks} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ResearchResultsPanel;
