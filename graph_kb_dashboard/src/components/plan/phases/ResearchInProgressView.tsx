'use client';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Loader2, FileText } from 'lucide-react';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import { ThinkingStepsPanel } from '../ThinkingStepsPanel';
import { ContextItemsPanel } from '../shared/ContextItemsPanel';
import type { ContextItems } from '../shared/ContextItemsPanel';
import { GeneratedArtifactsPanel } from '../shared/GeneratedArtifactsPanel';
import type { ThinkingStep } from '../PlanContext';
import type { PlanArtifactManifestEntry } from '@shared/websocket-events';

export interface ResearchInProgressViewProps {
    displayProgress: { percent: number; phase: string };
    displayContextCards: Record<string, unknown>[];
    agentContent?: string;
    thinkingSteps: ThinkingStep[];
    contextItems: unknown;
    artifacts: unknown;
    sessionId: string | undefined;
}

export function ResearchInProgressView({
    displayProgress,
    displayContextCards,
    agentContent,
    thinkingSteps,
    contextItems,
    artifacts,
    sessionId,
}: ResearchInProgressViewProps) {
    const progressPercent = typeof displayProgress?.percent === 'number' ? displayProgress.percent * 100 : 0;
    const progressPhase = displayProgress?.phase || 'Researching...';

    const contextPanel = contextItems
        ? <ContextItemsPanel contextItems={contextItems as ContextItems} sessionId={sessionId} />
        : null;
    const artifactsPanel = artifacts && (artifacts as unknown[]).length > 0
        ? <GeneratedArtifactsPanel artifacts={artifacts as PlanArtifactManifestEntry[]} sessionId={sessionId} />
        : null;

    return (
        <div className="w-full min-w-0 space-y-4">
            <div className="flex items-center gap-2">
                <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
                <h2 className="text-xl font-semibold">Research</h2>
            </div>
            <p className="text-sm text-muted-foreground">
                The agent is researching your requirements and identifying knowledge gaps.
            </p>
            {contextPanel}
            {artifactsPanel}

            {progressPercent > 0 && (
                <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                        <span>{progressPhase}</span>
                        <span>{Math.round(progressPercent)}%</span>
                    </div>
                    <Progress value={progressPercent} />
                </div>
            )}

            {displayContextCards.length > 0 && (
                <Card className="p-4">
                    <h4 className="font-medium mb-2 flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        Context Cards ({displayContextCards.length})
                    </h4>
                    <ScrollArea className="h-[200px]">
                        <div className="space-y-2">
                            {displayContextCards.slice(0, 3).map((card, i) => (
                                <div key={i} className="text-sm p-2 bg-muted/50 rounded">
                                    <span className="font-medium">{(card.title as string) || 'Card'}</span>
                                    <Badge variant="outline" className="ml-2">{(card.sourceType as string) || 'source'}</Badge>
                                </div>
                            ))}
                            {displayContextCards.length > 3 && (
                                <p className="text-xs text-muted-foreground">+{displayContextCards.length - 3} more...</p>
                            )}
                        </div>
                    </ScrollArea>
                </Card>
            )}

            {agentContent && (
                <Card className="p-6">
                    <MarkdownRenderer content={cleanAIText(agentContent)} />
                </Card>
            )}

            <ThinkingStepsPanel steps={thinkingSteps} />
        </div>
    );
}
