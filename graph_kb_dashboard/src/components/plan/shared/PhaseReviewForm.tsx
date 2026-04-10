'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Check, ArrowRight, Loader2, ArrowLeft } from 'lucide-react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import type { PhaseField } from '@shared/websocket-events';
import { PHASE_TITLES } from '../PlanContext';
import { FieldRenderer } from './FieldRenderer';
import { ResultValueRenderer } from './ResultValueRenderer';
import { cleanAIText } from '@/lib/utils/cleanAIText';

export interface PhaseReviewFormProps {
    phase: PlanPhaseId;
    nextPhase: string;
    result?: Record<string, unknown>;
    fields?: PhaseField[];
    message?: string;
    options?: Array<{ id: string; label: string }>;
    onSubmit: (data: Record<string, unknown>) => void;
    onClose?: () => void;
    /** Plan session ID — forwarded to FieldRenderer for plan-scoped uploads. */
    sessionId?: string | null;
}

/** Summary keys to hide from the rendered display. */
const HIDDEN_RESULT_KEYS = new Set(['evaluation_method']);

export function PhaseReviewForm({
    phase,
    nextPhase,
    result,
    fields = [],
    message,
    options,
    sessionId,
    onSubmit,
    onClose,
}: PhaseReviewFormProps) {
    const [formData, setFormData] = useState<Record<string, unknown>>({});
    const [isSubmitting, setIsSubmitting] = useState<string | null>(null);

    const updateField = (id: string, value: unknown) => {
        setFormData(prev => ({ ...prev, [id]: value }));
    };

    const handleContinue = () => {
        setIsSubmitting('continue');
        try {
            onSubmit({ decision: 'continue', ...formData });
        } finally {
            // Reset handled by unmount on success
        }
    };

    const handleRevise = () => {
        setIsSubmitting('revise');
        try {
            onSubmit({ decision: 'revise' });
        } finally {
            setIsSubmitting(null);
        }
    };

    const phaseDisplayName = PHASE_TITLES[phase as PlanPhaseId]?.title || phase;
    const nextPhaseDisplayName = PHASE_TITLES[nextPhase as PlanPhaseId]?.title || nextPhase;

    // Default options if not provided
    const displayOptions = options && options.length > 0
        ? options
        : [
            { id: 'continue', label: `Continue to ${nextPhaseDisplayName}` },
            { id: 'revise', label: 'Back' },
        ];

    return (
        <div className="max-w-3xl mx-auto space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            {/* Phase Complete Header */}
            <div className="flex items-center gap-3">
                <div className="flex items-center justify-center h-10 w-10 rounded-full bg-green-100 dark:bg-green-900/30">
                    <Check className="h-5 w-5 text-green-600 dark:text-green-400" />
                </div>
                <div>
                    <h2 className="text-xl font-semibold">{phaseDisplayName} Complete</h2>
                    <p className="text-sm text-muted-foreground">
                        Review the results below before continuing
                    </p>
                </div>
            </div>

            <Card className="p-6 space-y-5 border-green-200/50 dark:border-green-900/50 shadow-sm">
                {/* Message */}
                {message && (
                    <div className="text-base font-medium">{cleanAIText(message)}</div>
                )}

                {/* Result Summary */}
                {result && Object.keys(result).length > 0 && (() => {
                    const filtered = Object.fromEntries(
                        Object.entries(result).filter(([key]) => !HIDDEN_RESULT_KEYS.has(key))
                    );
                    return Object.keys(filtered).length > 0 ? (
                        <div className="bg-muted/50 rounded-lg p-4 space-y-3 text-sm border">
                            <h3 className="font-semibold text-foreground/90 mb-3">Results Summary</h3>
                            {Object.entries(filtered).map(([key, value]) => (
                                <div key={key} className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-4">
                                    <span className="text-muted-foreground font-medium min-w-[140px] capitalize shrink-0 pt-0.5">
                                        {key.replace(/_/g, ' ')}:
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <ResultValueRenderer keyName={key} value={value} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : null;
                })()}

                {/* Optional Input Fields for Next Phase */}
                {fields.length > 0 && (
                    <div className="space-y-4 pt-4 border-t">
                        <h3 className="font-semibold text-foreground/90">
                            Additional Inputs for {nextPhaseDisplayName}
                        </h3>
                        {fields.map(field => (
                            <FieldRenderer
                                key={field.id}
                                field={field}
                                value={formData[field.id]}
                                onChange={(val) => updateField(field.id, val)}
                                sessionId={sessionId}
                            />
                        ))}
                    </div>
                )}

                {/* Action Buttons */}
                <div className="flex flex-wrap gap-3 pt-4 border-t">
                    {/* Primary Continue Button */}
                    <Button
                        onClick={handleContinue}
                        disabled={isSubmitting !== null}
                        className="min-w-[160px]"
                    >
                        {isSubmitting === 'continue' ? (
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                            <ArrowRight className="h-4 w-4 mr-2" />
                        )}
                        Continue to {nextPhaseDisplayName}
                    </Button>

                    {/* Secondary Back Button */}
                    <Button
                        variant="outline"
                        onClick={onClose || handleRevise}
                        disabled={isSubmitting !== null}
                    >
                        {isSubmitting === 'revise' ? (
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                            <ArrowLeft className="h-4 w-4 mr-2" />
                        )}
                        Back
                    </Button>
                </div>
            </Card>
        </div>
    );
}
