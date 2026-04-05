'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import { ChevronRight } from 'lucide-react';
import type { KnowledgeGap } from '@/types/workflow';

const IMPACT_STYLES: Record<string, { badge: string; text: string }> = {
    high: { badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300', text: 'HIGH' },
    medium: { badge: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300', text: 'MEDIUM' },
    low: { badge: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400', text: 'LOW' },
};

const CATEGORY_ICONS: Record<string, string> = {
    scope: '🎯',
    technical: '⚙️',
    constraint: '🔒',
    stakeholder: '👥',
};

interface KnowledgeGapCardProps {
    gap: KnowledgeGap;
    /** Called when user provides an answer to a gap question. */
    onAnswer?: (gapId: string, questionIndex: number, answer: string) => void;
}

export function KnowledgeGapCard({ gap, onAnswer }: KnowledgeGapCardProps) {
    const [expanded, setExpanded] = useState(false);
    const [answers, setAnswers] = useState<Record<number, string>>({});
    const impact = IMPACT_STYLES[gap.impact] || IMPACT_STYLES.medium;

    const handleAnswer = (qIdx: number, value: string) => {
        setAnswers((prev) => ({ ...prev, [qIdx]: value }));
        onAnswer?.(gap.id, qIdx, value);
    };

    return (
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
            <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center gap-2 px-4 py-3 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-750 transition-colors text-left"
                aria-expanded={expanded}
            >
                <span className="text-base flex-shrink-0">{CATEGORY_ICONS[gap.category] || '❓'}</span>
                <span className="text-sm font-medium text-gray-800 dark:text-gray-200 flex-1">{gap.title}</span>
                <span className={cn('text-xs px-2 py-0.5 rounded-full font-semibold uppercase', impact.badge)}>
                    {impact.text}
                </span>
                <ChevronRight className={cn('w-4 h-4 text-gray-400 transition-transform', expanded && 'rotate-90')} />
            </button>

            {expanded && (
                <div className="px-4 py-3 space-y-3">
                    <p className="text-sm text-gray-600 dark:text-gray-300">{gap.description}</p>

                    {gap.questions.length > 0 && (
                        <div className="space-y-2">
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                Clarification Questions
                            </p>
                            {gap.questions.map((q: string, i: number) => (
                                <div key={i} className="space-y-1">
                                    <p className="text-sm text-gray-700 dark:text-gray-300">❓ {q}</p>
                                    {gap.suggestedAnswers.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5 ml-5">
                                            {gap.suggestedAnswers.map((sa: string, j: number) => (
                                                <button
                                                    key={j}
                                                    type="button"
                                                    onClick={() => handleAnswer(i, sa)}
                                                    className={cn(
                                                        'text-xs px-2.5 py-1 rounded-full border transition-colors',
                                                        answers[i] === sa
                                                            ? 'bg-blue-500 text-white border-blue-500'
                                                            : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-blue-50 dark:hover:bg-blue-900/20',
                                                    )}
                                                >
                                                    {sa}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    <input
                                        type="text"
                                        placeholder="Or type your answer..."
                                        value={answers[i] || ''}
                                        onChange={(e) => handleAnswer(i, e.target.value)}
                                        className="w-full ml-5 mt-1 px-3 py-1.5 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                                    />
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
