'use client';

import { useState, useCallback } from 'react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
    Check, Loader2, FileText, AlertTriangle, Sparkles,
    Ban, RotateCcw, MessageSquarePlus,
    ChevronDown, ChevronUp, Upload, X,
} from 'lucide-react';
import { useFileUpload, ACCEPTED_EXTENSIONS } from '@/hooks/useFileUpload';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import { KeyInsightsList } from '../shared/KeyInsightsList';
import { ContextItemsPanel } from '../shared/ContextItemsPanel';
import type { ContextItems } from '../shared/ContextItemsPanel';
import { GeneratedArtifactsPanel } from '../shared/GeneratedArtifactsPanel';
import type { PlanArtifactManifestEntry } from '@shared/websocket-events';

export interface ResearchCompleteViewProps {
    result?: Record<string, unknown>;
    displayContextCards: Record<string, unknown>[];
    displayGaps: Record<string, unknown>[];
    displayFindings: Record<string, unknown> | null;
    contextItems: unknown;
    artifacts: unknown;
    sessionId: string | undefined;
    onSubmit: (data: Record<string, unknown>) => void;
    isViewingPastPhase?: boolean;
    onNavigateToPhase?: (targetPhase: string) => void;
}

export function ResearchCompleteView({
    result,
    displayContextCards,
    displayGaps,
    displayFindings,
    contextItems,
    artifacts,
    sessionId,
    onSubmit,
    isViewingPastPhase,
    onNavigateToPhase,
}: ResearchCompleteViewProps) {
    const [activeTab, setActiveTab] = useState('context');
    const [dismissedGaps, setDismissedGaps] = useState<Set<string>>(new Set());
    const [showContextInput, setShowContextInput] = useState(false);
    const [contextText, setContextText] = useState('');
    const { uploadedFiles, isUploading, fileInputRef, handleInputChange, removeFile } = useFileUpload();
    const uploadedFile = uploadedFiles[0] ?? null;

    const handleGapDismiss = useCallback((gapId: string) => {
        setDismissedGaps(prev => {
            const next = new Set(prev);
            if (next.has(gapId)) next.delete(gapId);
            else next.add(gapId);
            return next;
        });
    }, []);

    const handleProvideContext = () => {
        const payload: Record<string, unknown> = {};
        if (contextText.trim()) payload.additional_context = contextText.trim();
        if (uploadedFile) payload.context_file_id = uploadedFile.id;
        if (dismissedGaps.size > 0) payload.dismissed_gaps = Array.from(dismissedGaps);
        if (Object.keys(payload).length > 0) onSubmit(payload);
    };

    const contextPanel = contextItems
        ? <ContextItemsPanel contextItems={contextItems as ContextItems} sessionId={sessionId} />
        : null;
    const artifactsPanel = artifacts && (artifacts as unknown[]).length > 0
        ? <GeneratedArtifactsPanel artifacts={artifacts as PlanArtifactManifestEntry[]} sessionId={sessionId} />
        : null;

    const markdown = typeof result?.markdown === 'string'
        ? result.markdown
        : typeof result?.summary === 'string'
            ? result.summary
            : null;

    return (
        <div className="max-w-3xl mx-auto space-y-4">
            <div className="flex items-center gap-2">
                <Check className="h-5 w-5 text-green-500" />
                <h2 className="text-xl font-semibold">Research Complete</h2>
            </div>
            {contextPanel}
            {artifactsPanel}

            {displayFindings && (
                <Card className="p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <Sparkles className="h-5 w-5 text-primary" />
                        <h3 className="font-semibold">Research Findings</h3>
                        {typeof displayFindings.confidenceScore === 'number' && (
                            <Badge variant="outline" className="ml-auto">
                                {Math.round(displayFindings.confidenceScore * 100)}% Confidence
                            </Badge>
                        )}
                    </div>
                    <MarkdownRenderer content={cleanAIText((displayFindings.summary as string) || '')} />
                    <KeyInsightsList insights={displayFindings.keyInsights} />
                </Card>
            )}

            {(displayContextCards.length > 0 || displayGaps.length > 0) && (
                <Tabs value={activeTab} onValueChange={setActiveTab}>
                    <TabsList className="w-full grid grid-cols-2">
                        <TabsTrigger value="context" className="flex items-center gap-2">
                            <FileText className="h-4 w-4" />
                            Context ({displayContextCards.length})
                        </TabsTrigger>
                        <TabsTrigger value="gaps" className="flex items-center gap-2">
                            <AlertTriangle className="h-4 w-4" />
                            Gaps ({displayGaps.length})
                        </TabsTrigger>
                    </TabsList>

                    <TabsContent value="context">
                        <ScrollArea className="h-[400px] pr-4">
                            <div className="space-y-4 py-4">
                                {displayContextCards.map((card, i) => (
                                    <Card key={(card.id as string) || `card-${i}`} className="p-4">
                                        <div className="flex items-center justify-between mb-2">
                                            <h4 className="font-medium">{(card.title as string) || 'Context Card'}</h4>
                                            <Badge variant="outline">{(card.sourceName as string) || (card.sourceType as string) || 'unknown'}</Badge>
                                        </div>
                                        <MarkdownRenderer content={cleanAIText((card.content as string) || (card.summary as string) || '')} />
                                    </Card>
                                ))}
                                {displayContextCards.length === 0 && (
                                    <div className="text-center py-8 text-muted-foreground text-sm">
                                        No context cards collected
                                    </div>
                                )}
                            </div>
                        </ScrollArea>
                    </TabsContent>

                    <TabsContent value="gaps">
                        <ScrollArea className="h-[400px] pr-4">
                            <div className="space-y-4 py-4">
                                {displayGaps.map((gap, i) => {
                                    const gapId = (gap.id as string) || `gap-${i}`;
                                    const isDismissed = dismissedGaps.has(gapId);
                                    return (
                                        <Card key={gapId} className={`group p-4 transition-all ${isDismissed ? 'opacity-50' : ''}`}>
                                            <div className="flex items-start gap-3">
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center justify-between mb-2">
                                                        <Badge>{(gap.category as string) || 'General'}</Badge>
                                                        <div className="flex items-center gap-2">
                                                            <Badge variant="outline">{(gap.impact as string) || 'Medium'}</Badge>
                                                            <button
                                                                type="button"
                                                                onClick={() => handleGapDismiss(gapId)}
                                                                className={`p-1 transition-opacity ${isDismissed ? 'text-muted-foreground hover:text-primary opacity-100' : 'text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100'}`}
                                                                aria-label={isDismissed ? 'Restore gap' : 'Dismiss gap'}
                                                            >
                                                                {isDismissed ? <RotateCcw className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                                                            </button>
                                                        </div>
                                                    </div>
                                                    <p className={`font-medium mb-2 ${isDismissed ? 'line-through' : ''}`}>{(gap.question as string) || ''}</p>
                                                    {!isDismissed && (gap.context as string) && (
                                                        <p className="text-sm text-muted-foreground">{(gap.context as string)}</p>
                                                    )}
                                                </div>
                                            </div>
                                        </Card>
                                    );
                                })}
                                {displayGaps.length === 0 && (
                                    <div className="text-center py-8 text-muted-foreground text-sm">
                                        No knowledge gaps detected
                                    </div>
                                )}
                            </div>
                        </ScrollArea>
                    </TabsContent>
                </Tabs>
            )}

            {/* Provide additional context or upload documents */}
            <Card className="p-4 border-dashed">
                <button
                    type="button"
                    onClick={() => setShowContextInput(!showContextInput)}
                    className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
                >
                    <MessageSquarePlus className="h-4 w-4" />
                    <span>Provide Additional Context</span>
                    {showContextInput
                        ? <ChevronUp className="h-4 w-4 ml-auto" />
                        : <ChevronDown className="h-4 w-4 ml-auto" />}
                </button>

                {showContextInput && (
                    <div className="mt-3 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                        <Textarea
                            placeholder="Add context, requirements, or reference material to address gaps..."
                            value={contextText}
                            onChange={(e) => setContextText(e.target.value)}
                            className="min-h-[80px] resize-y"
                        />
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept={ACCEPTED_EXTENSIONS}
                            onChange={handleInputChange}
                            className="hidden"
                        />
                        {uploadedFile ? (
                            <div className="border border-border rounded-md p-2 flex items-center gap-2 bg-muted/30">
                                <FileText className="h-4 w-4 text-green-500 shrink-0" />
                                <span className="text-xs font-medium truncate">{uploadedFile.filename}</span>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-6 w-6 p-0 ml-auto shrink-0"
                                    onClick={() => removeFile(uploadedFile.id)}
                                >
                                    <X className="h-3 w-3" />
                                </Button>
                            </div>
                        ) : (
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="text-xs"
                                disabled={isUploading}
                                onClick={() => fileInputRef.current?.click()}
                            >
                                {isUploading
                                    ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                                    : <Upload className="h-3.5 w-3.5 mr-1.5" />}
                                {isUploading ? 'Uploading...' : 'Attach File'}
                            </Button>
                        )}
                        <div className="flex justify-end pt-1">
                            <Button
                                size="sm"
                                disabled={!contextText.trim() && !uploadedFile}
                                onClick={handleProvideContext}
                            >
                                Submit Context
                            </Button>
                        </div>
                    </div>
                )}
            </Card>

            {markdown && displayContextCards.length === 0 && displayGaps.length === 0 && !displayFindings && (
                <Card className="p-6">
                    <MarkdownRenderer content={cleanAIText(markdown as string)} />
                </Card>
            )}

            {isViewingPastPhase && onNavigateToPhase && (
                <div className="flex justify-center pt-2">
                    <Button
                        variant="outline"
                        onClick={() => onNavigateToPhase('research')}
                        className="gap-2 text-sm border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20"
                    >
                        <RotateCcw className="h-4 w-4" />
                        Return to This Phase
                    </Button>
                </div>
            )}
        </div>
    );
}
