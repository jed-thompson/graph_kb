'use client';

import React, { useEffect, useCallback } from 'react';
import { X, Maximize2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ExpandableOverlayProps {
    /** Whether the overlay is currently open */
    isOpen: boolean;
    /** Callback when overlay should close */
    onClose: () => void;
    /** Title displayed in the overlay header */
    title: string;
    /** Optional subtitle */
    subtitle?: string;
    /** Content to display in the overlay */
    children: React.ReactNode;
    /** Size variant */
    size?: 'md' | 'lg' | 'xl' | 'full';
}

/**
 * Full-screen overlay modal for displaying expanded content.
 * Handles keyboard escape and click-outside to close.
 */
export function ExpandableOverlay({
    isOpen,
    onClose,
    title,
    subtitle,
    children,
    size = 'lg',
}: ExpandableOverlayProps) {
    // Handle escape key
    const handleKeyDown = useCallback((e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            onClose();
        }
    }, [onClose]);

    useEffect(() => {
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
            document.body.style.overflow = 'hidden';
        }
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = '';
        };
    }, [isOpen, handleKeyDown]);

    if (!isOpen) return null;

    const sizeClasses = {
        md: 'max-w-2xl',
        lg: 'max-w-4xl',
        xl: 'max-w-6xl',
        full: 'max-w-[95vw]',
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={onClose}
        >
            <div
                className={cn(
                    'w-full bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200',
                    sizeClasses[size]
                )}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                    <div>
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                            {title}
                        </h2>
                        {subtitle && (
                            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                                {subtitle}
                            </p>
                        )}
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                        aria-label="Close"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="max-h-[75vh] overflow-y-auto p-6">
                    {children}
                </div>
            </div>
        </div>
    );
}

interface ExpandableContentProps {
    /** Content to display (truncated if too long) */
    content: string;
    /** Maximum height before truncation (in tailwind units or pixels) */
    maxHeight?: string;
    /** Title for the overlay when expanded */
    title: string;
    /** Optional subtitle for overlay */
    subtitle?: string;
    /** Size of the overlay when expanded */
    overlaySize?: 'md' | 'lg' | 'xl' | 'full';
    /** Additional class names */
    className?: string;
    /** Custom render function for content */
    renderContent?: (content: string) => React.ReactNode;
    /** Line limit before showing "View More" (approximate) */
    lineLimit?: number;
}

/**
 * Content wrapper that shows a preview with "View More" button
 * if content exceeds the specified limit. Opens full content in overlay.
 */
export function ExpandableContent({
    content,
    maxHeight = 'max-h-48',
    title,
    subtitle,
    overlaySize = 'lg',
    className,
    renderContent,
    lineLimit = 10,
}: ExpandableContentProps) {
    const [isOverlayOpen, setIsOverlayOpen] = React.useState(false);
    const contentRef = React.useRef<HTMLDivElement>(null);
    const [needsExpansion, setNeedsExpansion] = React.useState(false);

    // Check if content exceeds the line limit
    useEffect(() => {
        if (contentRef.current) {
            const lineHeight = parseFloat(getComputedStyle(contentRef.current).lineHeight) || 20;
            const maxHeightPx = lineHeight * lineLimit;
            setNeedsExpansion(contentRef.current.scrollHeight > maxHeightPx + 20);
        }
    }, [content, lineLimit]);

    const renderedContent = renderContent ? renderContent(content) : (
        <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{content}</p>
    );

    return (
        <>
            <div className={cn('relative', className)}>
                <div
                    ref={contentRef}
                    className={cn(
                        'overflow-hidden transition-all duration-200',
                        maxHeight,
                        !needsExpansion && 'max-h-none'
                    )}
                >
                    {renderedContent}
                </div>

                {needsExpansion && (
                    <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-white dark:from-gray-900 to-transparent pointer-events-none" />
                )}

                {needsExpansion && (
                    <button
                        onClick={() => setIsOverlayOpen(true)}
                        className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
                    >
                        <Maximize2 className="w-3.5 h-3.5" />
                        View Full Content
                    </button>
                )}
            </div>

            <ExpandableOverlay
                isOpen={isOverlayOpen}
                onClose={() => setIsOverlayOpen(false)}
                title={title}
                subtitle={subtitle}
                size={overlaySize}
            >
                {renderedContent}
            </ExpandableOverlay>
        </>
    );
}

export default ExpandableOverlay;
