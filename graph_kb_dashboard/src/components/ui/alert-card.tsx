'use client';

import * as React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { AlertCircle, CheckCircle, AlertTriangle, Info, X } from 'lucide-react';

type AlertVariant = 'error' | 'success' | 'warning' | 'info';

interface AlertCardProps {
  /** Alert variant determines color scheme */
  variant?: AlertVariant;
  /** Main title text */
  title: string;
  /** Optional description text */
  description?: string;
  /** Optional retry button - pass onClick handler to show */
  onRetry?: () => void;
  /** Optional retry button text */
  retryText?: string;
  /** Optional dismiss button - pass onClick handler to show */
  onDismiss?: () => void;
  /** Optional className for custom styling */
  className?: string;
  /** Center align content */
  centered?: boolean;
}

const variantStyles: Record<AlertVariant, { card: string; text: string; icon: string }> = {
  error: {
    card: 'border-red-200 bg-red-50 dark:bg-red-900/10 dark:border-red-900',
    text: 'text-red-600 dark:text-red-400',
    icon: 'text-red-600 dark:text-red-400',
  },
  success: {
    card: 'border-green-300 bg-green-50 dark:bg-green-900/10 dark:border-green-800',
    text: 'text-green-600 dark:text-green-400',
    icon: 'text-green-600 dark:text-green-400',
  },
  warning: {
    card: 'border-amber-200 bg-amber-50 dark:bg-amber-900/10 dark:border-amber-800',
    text: 'text-amber-600 dark:text-amber-400',
    icon: 'text-amber-600 dark:text-amber-400',
  },
  info: {
    card: 'border-blue-200 bg-blue-50 dark:bg-blue-900/10 dark:border-blue-800',
    text: 'text-blue-600 dark:text-blue-400',
    icon: 'text-blue-600 dark:text-blue-400',
  },
};

const variantIcons: Record<AlertVariant, React.ElementType> = {
  error: AlertCircle,
  success: CheckCircle,
  warning: AlertTriangle,
  info: Info,
};

/**
 * A flexible alert card component for displaying status messages.
 *
 * @example
 * ```tsx
 * // Error with retry
 * <AlertCard
 *   variant="error"
 *   title="Error loading documents"
 *   description={errorMessage}
 *   onRetry={fetchDocuments}
 *   centered
 * />
 *
 * // Success banner with dismiss
 * <AlertCard
 *   variant="success"
 *   title="Upload complete"
 *   onDismiss={() => setStatus(null)}
 * />
 * ```
 */
export function AlertCard({
  variant = 'error',
  title,
  description,
  onRetry,
  retryText = 'Retry',
  onDismiss,
  className,
  centered = false,
}: AlertCardProps) {
  const styles = variantStyles[variant];
  const Icon = variantIcons[variant];

  return (
    <Card className={cn(styles.card, className)}>
      <CardContent className={cn('py-4', centered && 'text-center')}>
        <div className={cn('flex items-center gap-3', centered && 'justify-center')}>
          {!centered && <Icon className={cn('h-5 w-5 shrink-0', styles.icon)} />}
          <div className="flex-1">
            <p className={cn('font-medium', styles.text)}>{title}</p>
            {description && (
              <p className={cn('text-sm mt-1', styles.text, 'opacity-80')}>{description}</p>
            )}
            {(onRetry || centered) && onRetry && (
              <Button variant="outline" className="mt-4" onClick={onRetry}>
                {retryText}
              </Button>
            )}
          </div>
          {onDismiss && (
            <Button variant="ghost" size="sm" onClick={onDismiss}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
        {centered && onRetry && (
          <Button variant="outline" className="mt-4" onClick={onRetry}>
            {retryText}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default AlertCard;
