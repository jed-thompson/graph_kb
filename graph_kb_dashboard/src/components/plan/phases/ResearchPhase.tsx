'use client';

import { useState, useCallback } from 'react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Check, Loader2, FileText, AlertTriangle, Sparkles, BookOpen, Ban, RotateCcw, MessageSquarePlus, ChevronDown, ChevronUp, Upload, X } from 'lucide-react';
import { useFileUpload, ACCEPTED_EXTENSIONS } from '@/hooks/useFileUpload';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import { ThinkingStepsPanel } from '../ThinkingStepsPanel';
import { KeyInsightsList } from '../shared/KeyInsightsList';
import { PhaseInputForm } from '../shared/PhaseInputForm';
import { PhaseApprovalForm } from '../shared/PhaseApprovalForm';
import { PhaseReviewForm } from '../shared/PhaseReviewForm';
import { GeneratedArtifactsPanel } from '../shared/GeneratedArtifactsPanel';
import { ContextItemsPanel } from '../shared/ContextItemsPanel';
import type { ContextItems } from '../shared/ContextItemsPanel';
import { usePlanContext } from '../PlanContext';
import { useResearchStore } from '@/lib/store/researchStore';
import type { PlanPhaseId } from '@/lib/store/planStore';
import type { PhaseStatus, ThinkingStep, GateType } from '../PlanContext';

// Helper to extract research data from result
function extractResearchData(result: Record<string, unknown> | undefined) {
    if (!result) return { contextCards: [] as Record<string, unknown>[], gaps: [] as Record<string, unknown>[], findings: null, progress: { percent: 0, phase: 'idle' } };

    const contextCards = Array.isArray(result.context_cards)
        ? result.context_cards as Record<string, unknown>[]
        : Array.isArray(result.contextCards)
            ? result.contextCards as Record<string, unknown>[]
            : [];

    const gaps = Array.isArray(result.gaps)
        ? result.gaps as Record<string, unknown>[]
        : Array.isArray(result.knowledge_gaps)
            ? result.knowledge_gaps as Record<string, unknown>[]
            : [];

    const findings = (result.findings || null) as Record<string, unknown> | null;
    const progress = (result.progress || { percent: 0, phase: 'idle' }) as { percent: number; phase: string };

    return { contextCards, gaps, findings, progress };
}

interface ResearchPhaseProps {
    status: PhaseStatus;
    agentContent?: string;
    thinkingSteps: ThinkingStep[];
    result?: Record<string, unknown>;
    promptData?: {
        type?: GateType;
        fields?: import('../../../../../shared/websocket-events').PhaseField[];
        prefilled?: Record<string, unknown>;
        summary?: Record<string, unknown>;
        message?: string;
        options?: Array<{ id: string; label: string }>;
        result?: Record<string, unknown>;
        next_phase?: string;
        session_id?: string;
        // analysis_review fields
        completeness_score?: number;
        gaps?: Record<string, unknown> | unknown[];
        clarification_questions?: Record<string, unknown>[];
        suggested_actions?: string[];
        architecture_analysis?: Record<string, unknown>;
    };
    showThinking: boolean;
    isSubmitting: boolean;
    onToggleThinking: () => void;
    onSubmit: (data: Record<string, unknown>) => void;
    /** HITL callback to navigate back to a specific phase (triggers backend cascade) */
    onNavigateToPhase?: (targetPhase: string) => void;
    /** Whether the user is viewing a non-active phase */
    isViewingPastPhase?: boolean;
}

export function ResearchPhase({
    status,
    agentContent,
    thinkingSteps,
    result,
    promptData,
    // showThinking / onToggleThinking kept in interface for caller compat, no longer used
    isSubmitting,
    onSubmit,
    onNavigateToPhase,
    isViewingPastPhase,
}: ResearchPhaseProps) {
    const { artifacts, contextItems, sessionId } = usePlanContext();
    const contextPanel = contextItems ? (
        <ContextItemsPanel contextItems={contextItems as ContextItems} sessionId={sessionId} />
    ) : null;
    const artifactsPanel = artifacts && artifacts.length > 0
        ? <GeneratedArtifactsPanel artifacts={artifacts} sessionId={sessionId} />
        : null;

    const [activeTab, setActiveTab] = useState('context');
    const [dismissedGaps, setDismissedGaps] = useState<Set<string>>(new Set());
    const [showContextInput, setShowContextInput] = useState(false);
    const [contextText, setContextText] = useState('');

    const {
        uploadedFiles,
        isUploading,
        fileInputRef,
        handleInputChange,
        removeFile,
    } = useFileUpload();

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

    // Extract research data from result prop
    const { contextCards, gaps, findings, progress } = extractResearchData(result);

    // Also get data from useResearchStore for real-time updates during in_progress
    const researchStore = useResearchStore();
    const storeContextCards = researchStore.contextCards as unknown as Record<string, unknown>[];
    const storeGaps = researchStore.gaps as unknown as Record<string, unknown>[];
    const storeFindings = researchStore.findings as unknown as Record<string, unknown> | null;
    const storeProgress = researchStore.progress as { percent: number; phase: string };

    // Merge: prefer store data for in_progress, result data for complete
    const displayContextCards = status === 'in_progress' && storeContextCards.length > 0 ? storeContextCards : contextCards;
    const displayGaps = status === 'in_progress' && storeGaps.length > 0 ? storeGaps : gaps;
    const displayFindings = status === 'in_progress' && storeFindings ? storeFindings : findings;
    const displayProgress = status === 'in_progress' && storeProgress.percent > 0 ? storeProgress : progress;

    // Complete state with results
    if (status === 'complete' && (displayContextCards.length > 0 || displayGaps.length > 0 || displayFindings || result)) {
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
                        <MarkdownRenderer content={cleanAIText(markdown)} />
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

    // Phase has prompt — show input form, approval, or phase review
    if (promptData && !isSubmitting) {
        return (
            <div className="max-w-3xl mx-auto space-y-4">
                {contextPanel}
                {agentContent && promptData.type !== 'phase_review' && promptData.type !== 'approval' && (
                    <Card className="p-6">
                        <MarkdownRenderer content={cleanAIText(agentContent)} />
                    </Card>
                )}
                {promptData.type === 'phase_review' ? (
                    <PhaseReviewForm
                        phase="research"
                        nextPhase={promptData.next_phase || 'next'}
                        result={promptData.result}
                        fields={promptData.fields}
                        message={promptData.message}
                        options={promptData.options}
                        onSubmit={onSubmit}
                        sessionId={promptData.session_id}
                    />
                ) : promptData.type === 'approval' ? (
                    <PhaseApprovalForm
                        phase="research"
                        title="Research"
                        description="Review the research findings before proceeding."
                        summary={promptData.summary}
                        options={promptData.options}
                        message={promptData.message}
                        onSubmit={onSubmit}
                        initialDismissedGaps={dismissedGaps}
                    />
                ) : (
                    <PhaseInputForm
                        phase="research"
                        title="Research"
                        description="Please provide additional input for the research phase."
                        fields={promptData.fields || []}
                        prefilled={promptData.prefilled}
                        onSubmit={onSubmit}
                        sessionId={promptData.session_id}
                    />
                )}
            </div>
        );
    }

    // In progress state
    if (status === 'in_progress' || isSubmitting) {
        const progressPercent = typeof displayProgress?.percent === 'number' ? displayProgress.percent * 100 : 0;
        const progressPhase = displayProgress?.phase || 'Researching...';

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

    // Pending state
    return (
        <div className="max-w-3xl mx-auto text-center py-12">
            <BookOpen className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <h2 className="text-xl font-semibold text-muted-foreground">Research</h2>
            <p className="text-sm text-muted-foreground mt-2">
                This phase will begin once context gathering is complete.
            </p>
        </div>
    );
}
