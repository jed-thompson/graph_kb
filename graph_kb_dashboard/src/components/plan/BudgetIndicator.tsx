'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Coins, AlertTriangle, Save } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface BudgetIndicatorProps {
    budget: {
        remainingLlmCalls: number;
        tokensUsed: number;
        maxLlmCalls: number;
        maxTokens: number;
        remainingPct: number;
    };
    workflowStatus: string;
    onResume?: (newLimits: { max_llm_calls?: number; max_tokens?: number }) => void;
    onSaveAndClose?: () => void;
}

export function BudgetIndicator({ budget, workflowStatus, onResume, onSaveAndClose }: BudgetIndicatorProps) {
    const [showResumeForm, setShowResumeForm] = useState(false);
    const [newMaxCalls, setNewMaxCalls] = useState('');
    const [newMaxTokens, setNewMaxTokens] = useState('');

    const isWarning = budget.remainingPct < 0.2 && budget.remainingPct > 0;
    const isCritical = workflowStatus === 'budget_exhausted';
    const pctUsed = budget.maxLlmCalls > 0
        ? ((budget.maxLlmCalls - budget.remainingLlmCalls) / budget.maxLlmCalls) * 100
        : 0;

    const barColor = isCritical
        ? 'bg-red-500'
        : isWarning
            ? 'bg-amber-500'
            : 'bg-primary';

    const handleResume = () => {
        onResume?.({
            max_llm_calls: newMaxCalls ? parseInt(newMaxCalls, 10) : undefined,
            max_tokens: newMaxTokens ? parseInt(newMaxTokens, 10) : undefined,
        });
        setShowResumeForm(false);
    };

    if (budget.maxLlmCalls === 0 && budget.maxTokens === 0) return null;

    return (
        <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-card/50">
            <Coins className="h-4 w-4 text-muted-foreground flex-shrink-0" />

            <div className="flex items-center gap-3 flex-1 min-w-0">
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {budget.remainingLlmCalls}/{budget.maxLlmCalls} calls
                </span>

                <div className="w-24 h-1.5 bg-muted rounded-full overflow-hidden flex-shrink-0">
                    <div
                        className={`h-full rounded-full transition-all ${barColor}`}
                        style={{ width: `${pctUsed}%` }}
                    />
                </div>

                {budget.maxTokens > 0 && (
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {(budget.tokensUsed / 1000).toFixed(1)}k/{(budget.maxTokens / 1000).toFixed(0)}k tokens
                    </span>
                )}

                {isWarning && !isCritical && (
                    <Badge variant="outline" className="text-amber-600 border-amber-300 text-xs">
                        <AlertTriangle className="h-3 w-3 mr-1" />
                        Low budget
                    </Badge>
                )}

                {isCritical && (
                    <Badge variant="destructive" className="text-xs">
                        Budget exhausted
                    </Badge>
                )}
            </div>

            {isCritical && onResume && !showResumeForm && (
                <Button size="sm" variant="outline" onClick={() => setShowResumeForm(true)}>
                    Resume with more budget
                </Button>
            )}

            {onSaveAndClose && (
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button size="sm" variant="ghost" className="h-8 group" onClick={onSaveAndClose}>
                                <Save className="h-4 w-4 mr-2 text-muted-foreground group-hover:text-primary transition-colors" />
                                <span className="text-muted-foreground group-hover:text-primary transition-colors">Save & Close</span>
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent>Save progress and return to plan sessions</TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            )}

            {showResumeForm && (
                <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1">
                        <Label className="text-xs">Calls:</Label>
                        <Input
                            type="number"
                            value={newMaxCalls}
                            onChange={(e) => setNewMaxCalls(e.target.value)}
                            placeholder="200"
                            className="w-20 h-7 text-xs"
                        />
                    </div>
                    <div className="flex items-center gap-1">
                        <Label className="text-xs">Tokens:</Label>
                        <Input
                            type="number"
                            value={newMaxTokens}
                            onChange={(e) => setNewMaxTokens(e.target.value)}
                            placeholder="500000"
                            className="w-24 h-7 text-xs"
                        />
                    </div>
                    <Button size="sm" onClick={handleResume}>Go</Button>
                    <Button size="sm" variant="ghost" onClick={() => setShowResumeForm(false)}>Cancel</Button>
                </div>
            )}
        </div>
    );
}

export default BudgetIndicator;
