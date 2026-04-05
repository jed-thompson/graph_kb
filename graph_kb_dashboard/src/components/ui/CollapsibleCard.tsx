'use client';

import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface CollapsibleCardProps {
    /** Card title displayed in header */
    title: React.ReactNode;
    /** Optional subtitle or description */
    subtitle?: React.ReactNode;
    /** Icon to show before title */
    icon?: React.ReactNode;
    /** Badge or status indicator */
    badge?: React.ReactNode;
    /** Whether card starts expanded */
    defaultExpanded?: boolean;
    /** Controlled expanded state */
    expanded?: boolean;
    /** Callback when expansion changes */
    onExpandedChange?: (expanded: boolean) => void;
    /** Whether card is collapsible */
    collapsible?: boolean;
    /** Card content */
    children: React.ReactNode;
    /** Visual variant */
    variant?: 'default' | 'success' | 'warning' | 'info' | 'processing';
    /** Size variant */
    size?: 'sm' | 'md' | 'lg';
    /** Additional header actions */
    actions?: React.ReactNode;
    /** Custom class name */
    className?: string;
    /** Whether to show expand/collapse animation */
    animated?: boolean;
}

const variantStyles = {
    default: {
        container: 'bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-700',
        header: 'bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800',
        icon: 'text-gray-500 dark:text-gray-400',
        title: 'text-gray-900 dark:text-gray-100',
        subtitle: 'text-gray-500 dark:text-gray-400',
    },
    success: {
        container: 'bg-white dark:bg-gray-900 border-emerald-200 dark:border-emerald-800',
        header: 'bg-emerald-50 dark:bg-emerald-950/30 hover:bg-emerald-100 dark:hover:bg-emerald-950/50',
        icon: 'text-emerald-600 dark:text-emerald-400',
        title: 'text-emerald-900 dark:text-emerald-100',
        subtitle: 'text-emerald-600 dark:text-emerald-400',
    },
    warning: {
        container: 'bg-white dark:bg-gray-900 border-amber-200 dark:border-amber-800',
        header: 'bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-950/50',
        icon: 'text-amber-600 dark:text-amber-400',
        title: 'text-amber-900 dark:text-amber-100',
        subtitle: 'text-amber-600 dark:text-amber-400',
    },
    info: {
        container: 'bg-white dark:bg-gray-900 border-sky-200 dark:border-sky-800',
        header: 'bg-sky-50 dark:bg-sky-950/30 hover:bg-sky-100 dark:hover:bg-sky-950/50',
        icon: 'text-sky-600 dark:text-sky-400',
        title: 'text-sky-900 dark:text-sky-100',
        subtitle: 'text-sky-600 dark:text-sky-400',
    },
    processing: {
        container: 'bg-white dark:bg-gray-900 border-violet-200 dark:border-violet-800',
        header: 'bg-gradient-to-r from-violet-50 to-indigo-50 dark:from-violet-950/30 dark:to-indigo-950/30 hover:from-violet-100 hover:to-indigo-100 dark:hover:from-violet-950/50 dark:hover:to-indigo-950/50',
        icon: 'text-violet-600 dark:text-violet-400',
        title: 'text-violet-900 dark:text-violet-100',
        subtitle: 'text-violet-600 dark:text-violet-400',
    },
};

const sizeStyles = {
    sm: {
        container: 'rounded-lg',
        header: 'px-3 py-2',
        content: 'p-3',
        title: 'text-sm font-medium',
        subtitle: 'text-xs',
        icon: 'w-4 h-4',
        chevron: 'w-3.5 h-3.5',
    },
    md: {
        container: 'rounded-xl',
        header: 'px-4 py-3',
        content: 'p-4',
        title: 'text-base font-semibold',
        subtitle: 'text-sm',
        icon: 'w-5 h-5',
        chevron: 'w-4 h-4',
    },
    lg: {
        container: 'rounded-2xl',
        header: 'px-5 py-4',
        content: 'p-5',
        title: 'text-lg font-semibold',
        subtitle: 'text-sm',
        icon: 'w-6 h-6',
        chevron: 'w-5 h-5',
    },
};

export function CollapsibleCard({
    title,
    subtitle,
    icon,
    badge,
    defaultExpanded = true,
    expanded: controlledExpanded,
    onExpandedChange,
    collapsible = true,
    children,
    variant = 'default',
    size = 'md',
    actions,
    className,
    animated = true,
}: CollapsibleCardProps) {
    const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);

    const isExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded;
    const styles = variantStyles[variant];
    const sizes = sizeStyles[size];

    const handleToggle = () => {
        if (!collapsible) return;
        const newExpanded = !isExpanded;
        if (controlledExpanded === undefined) {
            setInternalExpanded(newExpanded);
        }
        onExpandedChange?.(newExpanded);
    };

    return (
        <div
            className={cn(
                'border shadow-sm overflow-hidden transition-all duration-200',
                styles.container,
                sizes.container,
                className
            )}
        >
            {/* Header */}
            <button
                type="button"
                onClick={handleToggle}
                disabled={!collapsible}
                className={cn(
                    'w-full flex items-center gap-3 transition-colors duration-150',
                    styles.header,
                    sizes.header,
                    collapsible && 'cursor-pointer',
                    !collapsible && 'cursor-default'
                )}
                aria-expanded={isExpanded}
            >
                {/* Expand/Collapse Chevron */}
                {collapsible && (
                    <span className="flex-shrink-0 transition-transform duration-200" style={{ transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}>
                        <ChevronDown className={cn('text-gray-400', sizes.chevron)} />
                    </span>
                )}

                {/* Icon */}
                {icon && (
                    <span className={cn('flex-shrink-0', styles.icon, sizes.icon)}>
                        {icon}
                    </span>
                )}

                {/* Title & Subtitle */}
                <div className="flex-1 min-w-0 text-left">
                    <div className={cn('flex items-center gap-2', sizes.title, styles.title)}>
                        {title}
                    </div>
                    {subtitle && (
                        <div className={cn('mt-0.5 truncate', sizes.subtitle, styles.subtitle)}>
                            {subtitle}
                        </div>
                    )}
                </div>

                {/* Badge */}
                {badge && (
                    <span className="flex-shrink-0">
                        {badge}
                    </span>
                )}

                {/* Actions */}
                {actions && (
                    <div className="flex-shrink-0 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        {actions}
                    </div>
                )}
            </button>

            {/* Content */}
            <div
                className={cn(
                    'grid transition-[grid-template-rows,opacity] duration-300 ease-in-out',
                    isExpanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                )}
            >
                <div className="overflow-hidden">
                    <div className={sizes.content}>
                        {children}
                    </div>
                </div>
            </div>
        </div>
    );
}

export default CollapsibleCard;
