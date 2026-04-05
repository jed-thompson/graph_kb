'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Loader2, ChevronDown, ChevronUp, Upload, X, FileText, MessageSquarePlus, AlertTriangle, Coins } from 'lucide-react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import { useFileUpload, ACCEPTED_EXTENSIONS } from '@/hooks/useFileUpload';
import { ResultValueRenderer } from './ResultValueRenderer';
import { TaskListRenderer } from './TaskListRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import type { TaskItem } from '../PlanContext';
import type { ItemFeedback } from './ArchitectureFeedbackItem';

/** Summary keys to hide from the rendered display. */
const HIDDEN_SUMMARY_KEYS = new Set(['evaluation_method', 'budget_exhausted', 'remaining_llm_calls', 'tokens_used', 'max_llm_calls', 'max_tokens', 'reason']);

interface BudgetSummary {
    budget_exhausted: boolean;
    reason?: string;
    remaining_llm_calls: number;
    tokens_used: number;
    max_llm_calls: number;
    max_tokens: number;
}

export interface PhaseApprovalFormProps {
    phase: PlanPhaseId;
    title: string;
    description: string;
    summary?: Record<string, unknown>;
    options?: Array<{id: string, label: string}>;
    message?: string;
    tasks?: TaskItem[];
    onSubmit: (data: Record<string, unknown>) => void;
    /** Pre-populated dismissed gap IDs (e.g. from a prior complete-state view). */
    initialDismissedGaps?: Set<string>;
}

export function PhaseApprovalForm({ title, description, summary, options, message, tasks, onSubmit, initialDismissedGaps }: PhaseApprovalFormProps) {
    const [isSubmitting, setIsSubmitting] = useState<string | null>(null);
    const [showContextInput, setShowContextInput] = useState(false);
    const [contextText, setContextText] = useState('');
    const [gapFeedback, setGapFeedback] = useState<Record<string, ItemFeedback>>({});
    const [dismissedGaps, setDismissedGaps] = useState<Set<string>>(initialDismissedGaps ?? new Set());

    // Budget interrupt state
    const [showBudgetForm, setShowBudgetForm] = useState(false);
    const [newMaxCalls, setNewMaxCalls] = useState('');
    const [newMaxTokens, setNewMaxTokens] = useState('');

    const {
        uploadedFiles,
        isUploading,
        fileInputRef,
        handleInputChange,
        removeFile,
    } = useFileUpload();

    const uploadedFile = uploadedFiles[0] ?? null;

    // Budget interrupt detection
    const isBudgetInterrupt = (summary?.budget_exhausted as boolean) === true;
    const budgetData = isBudgetInterrupt ? summary as unknown as BudgetSummary : null;

    // Default increase values (50% bump, matching backend fallback)
    const defaultMaxCalls = budgetData
        ? budgetData.max_llm_calls + Math.max(Math.floor(budgetData.max_llm_calls * 0.5), 10)
        : 0;
    const defaultMaxTokens = budgetData && budgetData.max_tokens > 0
        ? budgetData.max_tokens + Math.floor(budgetData.max_tokens * 0.5)
        : 0;

    const handleGapFeedback = (gapId: string, feedback: ItemFeedback) => {
        setGapFeedback(prev => ({ ...prev, [gapId]: feedback }));
    };

    const handleGapDismiss = (gapId: string) => {
        setDismissedGaps(prev => {
            const next = new Set(prev);
            if (next.has(gapId)) next.delete(gapId);
            else next.add(gapId);
            return next;
        });
    };

    const handleOptionSubmit = (optionId: string) => {
        setIsSubmitting(optionId);
        try {
            const payload: Record<string, unknown> = { decision: optionId };
            if (contextText.trim()) payload.additional_context = contextText.trim();
            if (uploadedFile) payload.context_file_id = uploadedFile.id;
            const populatedFeedback = Object.fromEntries(
                Object.entries(gapFeedback).filter(([, v]) => v.note || v.fileId)
            );
            if (Object.keys(populatedFeedback).length > 0) {
                payload.gap_responses = populatedFeedback;
            }
            if (dismissedGaps.size > 0) {
                payload.dismissed_gaps = Array.from(dismissedGaps);
            }
            onSubmit(payload);
        } finally {
            // Optional: reset state on failure, but handled by unmount if success
        }
    };

    const handleBudgetConfirm = () => {
        const calls = newMaxCalls ? parseInt(newMaxCalls, 10) : defaultMaxCalls;
        const tokens = newMaxTokens ? parseInt(newMaxTokens, 10) : undefined;

        if (!calls || calls <= (budgetData?.max_llm_calls ?? 0)) return;

        setIsSubmitting('increase_budget');
        const payload: Record<string, unknown> = { decision: 'increase_budget' };
        payload.max_llm_calls = calls;
        if (tokens && tokens > 0) payload.max_tokens = tokens;
        if (contextText.trim()) payload.additional_context = contextText.trim();
        if (uploadedFile) payload.context_file_id = uploadedFile.id;
        onSubmit(payload);
    };

    const filteredSummary = summary
        ? Object.fromEntries(Object.entries(summary).filter(([key]) => !HIDDEN_SUMMARY_KEYS.has(key)))
        : undefined;

    return (
        <div className="max-w-3xl mx-auto space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div>
                <h2 className="text-xl font-semibold">{title}</h2>
                <p className="text-sm text-muted-foreground mt-1">{description}</p>
            </div>

            <Card className={`p-6 space-y-5 shadow-sm ${isBudgetInterrupt ? 'border-amber-300/60 dark:border-amber-800/60' : 'border-blue-200/50 dark:border-blue-900/50'}`}>
                {message && (
                    <div className="text-base font-medium">{cleanAIText(message)}</div>
                )}

                {/* Budget exhaustion usage card */}
                {isBudgetInterrupt && budgetData && (
                    <div className="bg-amber-50 dark:bg-amber-950/30 rounded-lg p-4 space-y-3 text-sm border border-amber-200/60 dark:border-amber-900/60">
                        <div className="flex items-center gap-2">
                            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                            <Badge variant="outline" className="text-amber-700 border-amber-400 dark:text-amber-300 dark:border-amber-600 text-xs">
                                Budget Exhausted
                            </Badge>
                        </div>

                        {budgetData.reason && (
                            <p className="text-xs text-muted-foreground">{cleanAIText(budgetData.reason)}</p>
                        )}

                        <div className="space-y-2 pt-1">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2 min-w-0">
                                    <Coins className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                                    <span className="text-xs text-muted-foreground">LLM Calls</span>
                                </div>
                                <span className="text-xs font-medium tabular-nums">
                                    {budgetData.max_llm_calls - budgetData.remaining_llm_calls}/{budgetData.max_llm_calls}
                                    <span className="text-muted-foreground ml-1">(100%)</span>
                                </span>
                            </div>
                            <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                                <div className="h-full rounded-full bg-red-500" style={{ width: '100%' }} />
                            </div>

                            {budgetData.max_tokens > 0 && (
                                <div className="flex items-center justify-between pt-1">
                                    <span className="text-xs text-muted-foreground">Tokens</span>
                                    <span className="text-xs font-medium tabular-nums">
                                        {(budgetData.tokens_used / 1000).toFixed(1)}k / {(budgetData.max_tokens / 1000).toFixed(0)}k
                                    </span>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {filteredSummary && Object.keys(filteredSummary).length > 0 && (
                    <div className="bg-muted/50 rounded-lg p-4 space-y-3 text-sm border">
                        {Object.entries(filteredSummary).map(([key, value]) => (
                            <div key={key} className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-4">
                                <span className="text-muted-foreground font-medium min-w-[140px] capitalize shrink-0 pt-0.5">
                                    {key.replace(/_/g, ' ')}:
                                </span>
                                <div className="flex-1 min-w-0">
                                    <ResultValueRenderer
                                        keyName={key}
                                        value={value}
                                        onGapFeedback={handleGapFeedback}
                                        gapFeedbackValues={gapFeedback}
                                        onGapDismiss={handleGapDismiss}
                                        dismissedGapIds={dismissedGaps}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {tasks && tasks.length > 0 && (
                    <div className="space-y-2">
                        <h3 className="text-sm font-medium">Tasks</h3>
                        <TaskListRenderer tasks={tasks} />
                    </div>
                )}

                {/* Inline context toggle */}
                <div className="border-t pt-3">
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
                                placeholder="Add context, requirements, or reference material to help the next phase..."
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
                        </div>
                    )}
                </div>

                {/* Budget increase inline form */}
                {isBudgetInterrupt && showBudgetForm ? (
                    <div className="border-t pt-4 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                        <p className="text-sm font-medium">Set new budget limits</p>
                        <div className="flex flex-wrap items-end gap-3">
                            <div className="flex items-center gap-1.5">
                                <Label htmlFor="budget-calls" className="text-xs">Max LLM Calls:</Label>
                                <Input
                                    id="budget-calls"
                                    type="number"
                                    value={newMaxCalls}
                                    onChange={(e) => setNewMaxCalls(e.target.value)}
                                    placeholder={String(defaultMaxCalls)}
                                    className="w-24 h-8 text-xs"
                                    min={budgetData ? budgetData.max_llm_calls + 1 : 1}
                                />
                            </div>
                            {budgetData && budgetData.max_tokens > 0 && (
                                <div className="flex items-center gap-1.5">
                                    <Label htmlFor="budget-tokens" className="text-xs">Max Tokens:</Label>
                                    <Input
                                        id="budget-tokens"
                                        type="number"
                                        value={newMaxTokens}
                                        onChange={(e) => setNewMaxTokens(e.target.value)}
                                        placeholder={String(defaultMaxTokens)}
                                        className="w-28 h-8 text-xs"
                                        min={budgetData.max_tokens + 1}
                                    />
                                </div>
                            )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                            Leave blank to use defaults (+50%: {defaultMaxCalls} calls{budgetData && budgetData.max_tokens > 0 ? `, ${defaultMaxTokens} tokens` : ''})
                        </p>
                        <div className="flex flex-wrap gap-3">
                            <Button
                                onClick={handleBudgetConfirm}
                                disabled={isSubmitting !== null}
                            >
                                {isSubmitting === 'increase_budget' && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                                Confirm & Continue
                            </Button>
                            <Button
                                variant="ghost"
                                onClick={() => setShowBudgetForm(false)}
                                disabled={isSubmitting !== null}
                            >
                                Cancel
                            </Button>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-wrap gap-3 pt-4 border-t">
                        {options && options.length > 0 ? options.map(opt => {
                            const isPrimary = opt.id === 'approve' || opt.label.toLowerCase().includes('approve');
                            const isBudgetIncrease = isBudgetInterrupt && opt.id === 'increase_budget';
                            return (
                                <Button
                                    key={opt.id}
                                    onClick={() => {
                                        if (isBudgetIncrease) {
                                            setShowBudgetForm(true);
                                        } else {
                                            handleOptionSubmit(opt.id);
                                        }
                                    }}
                                    disabled={isSubmitting !== null}
                                    variant={isPrimary || isBudgetIncrease ? 'default' : 'secondary'}
                                    className={isPrimary || isBudgetIncrease ? 'min-w-[120px]' : ''}
                                >
                                    {isSubmitting === opt.id && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                                    {opt.label}
                                </Button>
                            );
                        }) : (
                            <Button onClick={() => handleOptionSubmit('approve')} disabled={isSubmitting !== null}>
                                {isSubmitting === 'approve' && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                                Approve & Continue
                            </Button>
                        )}
                    </div>
                )}
            </Card>
        </div>
    );
}
