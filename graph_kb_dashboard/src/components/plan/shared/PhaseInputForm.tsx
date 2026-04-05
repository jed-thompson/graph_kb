'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Loader2 } from 'lucide-react';
import type { PlanPhaseId } from '@/lib/store/planStore';
import type { PhaseField } from '@shared/websocket-events';
import { FieldRenderer } from './FieldRenderer';

export interface PhaseInputFormProps {
    phase: PlanPhaseId;
    title: string;
    description: string;
    fields: PhaseField[];
    prefilled?: Record<string, unknown>;
    onSubmit: (data: Record<string, unknown>) => void;
    /** Plan session ID — forwarded to FieldRenderer for plan-scoped uploads. */
    sessionId?: string | null;
}

export function PhaseInputForm({ title, description, fields, prefilled, onSubmit, sessionId }: PhaseInputFormProps) {
    const [formData, setFormData] = useState<Record<string, unknown>>(() => {
        const initial: Record<string, unknown> = {};
        for (const field of fields) {
            initial[field.id] = prefilled?.[field.id] ?? '';
        }
        return initial;
    });
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [isSubmitting, setIsSubmitting] = useState(false);

    const updateField = (id: string, value: unknown) => {
        setFormData(prev => ({ ...prev, [id]: value }));
        setErrors(prev => {
            const next = { ...prev };
            delete next[id];
            return next;
        });
    };

    const handleSubmit = () => {
        const newErrors: Record<string, string> = {};
        for (const field of fields) {
            if (field.required) {
                const val = formData[field.id];
                if (!val || (typeof val === 'string' && !val.trim())) {
                    newErrors[field.id] = `${field.label} is required`;
                }
            }
        }
        if (Object.keys(newErrors).length > 0) {
            setErrors(newErrors);
            return;
        }
        setIsSubmitting(true);
        try {
            onSubmit(formData);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="max-w-3xl mx-auto space-y-6">
            <div>
                <h2 className="text-xl font-semibold">{title}</h2>
                <p className="text-sm text-muted-foreground mt-1">{description}</p>
            </div>

            <Card className="p-6 space-y-5">
                {fields.map(field => (
                    <FieldRenderer
                        key={field.id}
                        field={field}
                        value={formData[field.id]}
                        error={errors[field.id]}
                        onChange={(val) => updateField(field.id, val)}
                        sessionId={sessionId}
                    />
                ))}

                <div className="flex justify-end pt-2">
                    <Button onClick={handleSubmit} disabled={isSubmitting}>
                        {isSubmitting ? (
                            <>
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                Submitting...
                            </>
                        ) : (
                            'Continue'
                        )}
                    </Button>
                </div>
            </Card>
        </div>
    );
}
