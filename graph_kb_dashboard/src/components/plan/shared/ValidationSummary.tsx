'use client';

import React, { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronUp, CheckCircle2, XCircle } from 'lucide-react';

export interface ValidationSummaryProps {
    isValid: boolean;
    errors?: Array<Record<string, unknown>> | string[];
    warnings?: Array<Record<string, unknown>> | string[];
    errorsCount: number;
    warningsCount: number;
}

export function ValidationSummary({ isValid, errors, warnings, errorsCount, warningsCount }: ValidationSummaryProps) {
    const actualErrorCount = errors?.length ?? errorsCount;
    const actualWarningCount = warnings?.length ?? warningsCount;
    const hasErrorDetails = errors && errors.length > 0;
    const hasWarningDetails = warnings && warnings.length > 0;

    const [errorsExpanded, setErrorsExpanded] = useState(actualErrorCount > 0);
    const [warningsExpanded, setWarningsExpanded] = useState(false);

    const formatItem = (item: Record<string, unknown> | string): string => {
        if (typeof item === 'string') return item;
        return (item.message as string) || (item.description as string) || (item.rule as string) || JSON.stringify(item);
    };

    const sectionOf = (item: Record<string, unknown> | string): string | null => {
        if (typeof item === 'string') return null;
        return (item.section as string) || (item.location as string) || null;
    };

    return (
        <div className="space-y-2">
            {/* Status badge */}
            <div className="flex items-center gap-2">
                {isValid
                    ? <CheckCircle2 className="h-4 w-4 text-green-500" />
                    : <XCircle className="h-4 w-4 text-red-500" />}
                <span className={`text-sm font-medium ${isValid ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-400'}`}>
                    {isValid ? 'Validation passed' : 'Validation issues found'}
                </span>
            </div>

            {/* Errors */}
            {actualErrorCount > 0 && (
                <div className="rounded-lg border border-red-200 dark:border-red-900 overflow-hidden">
                    <button
                        type="button"
                        onClick={() => hasErrorDetails && setErrorsExpanded(!errorsExpanded)}
                        className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-medium bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-400 ${hasErrorDetails ? 'hover:bg-red-100 dark:hover:bg-red-950/50 cursor-pointer' : 'cursor-default'} transition-colors`}
                    >
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>{actualErrorCount} {actualErrorCount === 1 ? 'error' : 'errors'}</span>
                        {hasErrorDetails && (
                            errorsExpanded
                                ? <ChevronUp className="h-3.5 w-3.5 ml-auto" />
                                : <ChevronDown className="h-3.5 w-3.5 ml-auto" />
                        )}
                        {!hasErrorDetails && (
                            <span className="ml-auto text-[10px] text-red-400">re-run to see details</span>
                        )}
                    </button>
                    {errorsExpanded && hasErrorDetails && (
                        <ul className="px-3 py-2 space-y-1.5 text-xs">
                            {errors.map((err, i) => (
                                <li key={i} className="flex gap-2">
                                    <span className="text-red-400 shrink-0 pt-0.5">•</span>
                                    <div>
                                        <span className="text-foreground">{formatItem(err)}</span>
                                        {sectionOf(err) && (
                                            <span className="text-muted-foreground ml-1">({sectionOf(err)})</span>
                                        )}
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}

            {/* Warnings */}
            {actualWarningCount > 0 && (
                <div className="rounded-lg border border-amber-200 dark:border-amber-900 overflow-hidden">
                    <button
                        type="button"
                        onClick={() => hasWarningDetails && setWarningsExpanded(!warningsExpanded)}
                        className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-medium bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400 ${hasWarningDetails ? 'hover:bg-amber-100 dark:hover:bg-amber-950/50 cursor-pointer' : 'cursor-default'} transition-colors`}
                    >
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>{actualWarningCount} {actualWarningCount === 1 ? 'warning' : 'warnings'}</span>
                        {hasWarningDetails && (
                            warningsExpanded
                                ? <ChevronUp className="h-3.5 w-3.5 ml-auto" />
                                : <ChevronDown className="h-3.5 w-3.5 ml-auto" />
                        )}
                        {!hasWarningDetails && (
                            <span className="ml-auto text-[10px] text-amber-400">re-run to see details</span>
                        )}
                    </button>
                    {warningsExpanded && hasWarningDetails && (
                        <ul className="px-3 py-2 space-y-1.5 text-xs">
                            {warnings.map((warn, i) => (
                                <li key={i} className="flex gap-2">
                                    <span className="text-amber-400 shrink-0 pt-0.5">•</span>
                                    <div>
                                        <span className="text-foreground">{formatItem(warn)}</span>
                                        {sectionOf(warn) && (
                                            <span className="text-muted-foreground ml-1">({sectionOf(warn)})</span>
                                        )}
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
}
