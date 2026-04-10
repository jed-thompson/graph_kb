'use client';

import React from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader2 } from 'lucide-react';

interface BudgetData {
    budget_exhausted: boolean;
    reason?: string;
    remaining_llm_calls: number;
    tokens_used: number;
    max_llm_calls: number;
    max_tokens: number;
}

export interface ApprovalActionsProps {
    options?: Array<{ id: string; label: string }>;
    isSubmitting: string | null;
    isBudgetInterrupt: boolean;
    budgetData: BudgetData | null;
    showBudgetForm: boolean;
    onShowBudgetForm: (show: boolean) => void;
    onOptionSubmit: (optionId: string) => void;
    onBudgetConfirm: () => void;
    /** Controlled value for new max LLM calls input. */
    newMaxCalls: string;
    onNewMaxCallsChange: (value: string) => void;
    /** Controlled value for new max tokens input. */
    newMaxTokens: string;
    onNewMaxTokensChange: (value: string) => void;
    /** Default max calls value (50% bump). */
    defaultMaxCalls: number;
    /** Default max tokens value (50% bump). */
    defaultMaxTokens: number;
}

export function ApprovalActions({
    options,
    isSubmitting,
    isBudgetInterrupt,
    budgetData,
    showBudgetForm,
    onShowBudgetForm,
    onOptionSubmit,
    onBudgetConfirm,
    newMaxCalls,
    onNewMaxCallsChange,
    newMaxTokens,
    onNewMaxTokensChange,
    defaultMaxCalls,
    defaultMaxTokens,
}: ApprovalActionsProps) {
    if (isBudgetInterrupt && showBudgetForm) {
        return (
            <div className="border-t pt-4 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                <p className="text-sm font-medium">Set new budget limits</p>
                <div className="flex flex-wrap items-end gap-3">
                    <div className="flex items-center gap-1.5">
                        <Label htmlFor="budget-calls" className="text-xs">Max LLM Calls:</Label>
                        <Input
                            id="budget-calls"
                            type="number"
                            value={newMaxCalls}
                            onChange={(e) => onNewMaxCallsChange(e.target.value)}
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
                                onChange={(e) => onNewMaxTokensChange(e.target.value)}
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
                        onClick={onBudgetConfirm}
                        disabled={isSubmitting !== null}
                    >
                        {isSubmitting === 'increase_budget' && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                        Confirm & Continue
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={() => onShowBudgetForm(false)}
                        disabled={isSubmitting !== null}
                    >
                        Cancel
                    </Button>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-wrap gap-3 pt-4 border-t">
            {options && options.length > 0 ? options.map(opt => {
                const isPrimary = opt.id === 'approve' || opt.label.toLowerCase().includes('approve');
                const isBudgetIncrease = isBudgetInterrupt && opt.id === 'increase_budget';
                return (
                    <Button
                        key={opt.id}
                        onClick={() => {
                            if (isBudgetIncrease) {
                                onShowBudgetForm(true);
                            } else {
                                onOptionSubmit(opt.id);
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
                <Button onClick={() => onOptionSubmit('approve')} disabled={isSubmitting !== null}>
                    {isSubmitting === 'approve' && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                    Approve & Continue
                </Button>
            )}
        </div>
    );
}
