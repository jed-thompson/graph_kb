'use client';

import React, { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, Coins, CheckCircle2, XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import { useFileUpload } from '@/hooks/useFileUpload';
import { getWebSocket } from '@/lib/api/websocket';
import { ResultValueRenderer } from './ResultValueRenderer';
import { TaskListRenderer } from './TaskListRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';
import type { TaskItem } from '../PlanContext';
import type { ItemFeedback } from './ArchitectureFeedbackItem';
import { ApprovalActions } from './ApprovalActions';
import { ApprovalFeedbackInput } from './ApprovalFeedbackInput';
import { AssemblyDocumentPreview } from './AssemblyDocumentPreview';
import { ValidationSummary } from './ValidationSummary';

/** Summary keys to hide from the generic key-value display. */
const HIDDEN_SUMMARY_KEYS = new Set([
    'evaluation_method', 'budget_exhausted', 'remaining_llm_calls', 'tokens_used',
    'max_llm_calls', 'max_tokens', 'reason', 'document_preview', 'manifest_entries',
    // Rendered by dedicated components instead of raw key-value
    'errors', 'warnings', 'errors_count', 'warnings_count',
    'spec_document_path', 'is_valid',
]);

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
    /** Plan session ID for artifact downloads. */
    sessionId?: string | null;
    /** Callback to navigate to a phase (used for assembly revise via plan.navigate). */
    onNavigateToPhase?: (targetPhase: string) => void;
}

export function PhaseApprovalForm({ phase, title, description, summary, options, message, tasks, onSubmit, initialDismissedGaps, sessionId, onNavigateToPhase }: PhaseApprovalFormProps) {
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
        // For assembly revise, use navigate instead of phase input
        // so the workflow re-enters assembly from scratch (reset state, re-run LLM).
        // Use confirm_cascade:true since assembly has no downstream phases.
        console.log('[PhaseApprovalForm] handleOptionSubmit', { optionId, phase, sessionId: sessionId ?? 'NULL' });
        if (optionId === 'revise' && phase === 'assembly' && sessionId) {
            setIsSubmitting(optionId);

            const socket = getWebSocket();
            if (socket) {
                const navigatePayload: Record<string, unknown> = {
                    session_id: sessionId,
                    target_phase: 'assembly',
                    confirm_cascade: true,
                };
                if (contextText.trim()) navigatePayload.feedback = contextText.trim();
                if (uploadedFile) navigatePayload.context_file_id = uploadedFile.id;

                socket.send({
                    type: 'plan.navigate',
                    payload: navigatePayload,
                });
            }
            return;
        }

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

    const tasksSection: React.ReactNode = tasks && tasks.length > 0 ? (
        <div className="space-y-2">
            <h3 className="text-sm font-medium">Tasks</h3>
            <TaskListRenderer tasks={tasks} />
        </div>
    ) : null;

    const assemblyPreview: React.ReactNode = phase === 'assembly' && (summary?.document_preview || summary?.manifest_entries) ? (
        <AssemblyDocumentPreview
            documentPreview={summary.document_preview as string | undefined}
            manifestEntries={summary.manifest_entries as Array<Record<string, unknown>> | undefined}
            specName={summary.spec_name as string | undefined}
            sessionId={sessionId}
        />
    ) : null;

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
                    <BudgetExhaustionCard budgetData={budgetData} />
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

                {tasksSection}

                {/* Validation errors and warnings */}
                {summary && (
                    (summary.errors as unknown[])?.length > 0
                    || (summary.warnings as unknown[])?.length > 0
                    || (summary.errors_count as number) > 0
                    || (summary.warnings_count as number) > 0
                ) && (
                    <ValidationSummary
                        isValid={summary.is_valid as boolean ?? true}
                        errors={summary.errors as Array<Record<string, unknown>> | string[] | undefined}
                        warnings={summary.warnings as Array<Record<string, unknown>> | string[] | undefined}
                        errorsCount={(summary.errors_count as number) || 0}
                        warningsCount={(summary.warnings_count as number) || 0}
                    />
                )}

                {/* Assembly document preview + download */}
                {assemblyPreview}

                {/* Inline context / feedback input */}
                <ApprovalFeedbackInput
                    showContextInput={showContextInput}
                    onToggleContextInput={() => setShowContextInput(!showContextInput)}
                    contextText={contextText}
                    onContextTextChange={setContextText}
                    uploadedFile={uploadedFile}
                    isUploading={isUploading}
                    fileInputRef={fileInputRef}
                    onFileInputChange={handleInputChange}
                    onRemoveFile={removeFile}
                />

                {/* Approve / reject / revise buttons + budget form */}
                <ApprovalActions
                    options={options}
                    isSubmitting={isSubmitting}
                    isBudgetInterrupt={isBudgetInterrupt}
                    budgetData={budgetData}
                    showBudgetForm={showBudgetForm}
                    onShowBudgetForm={setShowBudgetForm}
                    onOptionSubmit={handleOptionSubmit}
                    onBudgetConfirm={handleBudgetConfirm}
                    newMaxCalls={newMaxCalls}
                    onNewMaxCallsChange={setNewMaxCalls}
                    newMaxTokens={newMaxTokens}
                    onNewMaxTokensChange={setNewMaxTokens}
                    defaultMaxCalls={defaultMaxCalls}
                    defaultMaxTokens={defaultMaxTokens}
                />
            </Card>
        </div>
    );
}

// ── Budget Exhaustion Card (private to this module) ──────────────────

function BudgetExhaustionCard({ budgetData }: { budgetData: BudgetSummary }) {
    return (
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
    );
}
