'use client';

import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';
import {
  Clock,
  Loader2,
  CheckCircle,
  AlertCircle
} from 'lucide-react';

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold transition-all duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground shadow-sm hover:bg-primary/80',
        secondary:
          'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive:
          'border-transparent bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/80',
        outline:
          'text-foreground',
        success:
          'border-transparent bg-emerald-500 text-white shadow-sm',
        warning:
          'border-transparent bg-amber-500 text-amber-900 shadow-sm',
        info:
          'border-transparent bg-sky-500 text-sky-50 shadow-sm',
        // Status-specific variants
        pending:
          'border-transparent bg-amber-100 text-amber-700 shadow-sm border border-amber-200',
        cloning:
          'border-transparent bg-violet-100 text-violet-700 shadow-sm border border-violet-200',
        indexing:
          'border-transparent bg-sky-100 text-sky-700 shadow-sm border border-sky-200',
        paused:
          'border-transparent bg-gray-100 text-gray-700 shadow-sm border border-gray-200',
        ready:
          'border-transparent bg-emerald-100 text-emerald-700 shadow-sm border border-emerald-200',
        error:
          'border-transparent bg-rose-100 text-rose-700 shadow-sm border border-rose-200',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };

/* Enhanced StatusBadge with icons and animations */
interface StatusBadgeProps {
  status: 'pending' | 'cloning' | 'indexing' | 'paused' | 'ready' | 'error';
  showDot?: boolean;
  className?: string;
}

export function StatusBadge({ status, showDot = true, className }: StatusBadgeProps) {
  const config = {
    pending: {
      label: 'Pending',
      icon: <Clock className="h-3 w-3 text-amber-600" />,
      dotColor: 'bg-amber-400'
    },
    cloning: {
      label: 'Cloning',
      icon: <Loader2 className="h-3 w-3 text-violet-600 animate-spin" />,
      dotColor: 'bg-violet-400 animate-pulse'
    },
    indexing: {
      label: 'Indexing',
      icon: <Loader2 className="h-3 w-3 text-sky-600 animate-spin" />,
      dotColor: 'bg-sky-400 animate-pulse'
    },
    paused: {
      label: 'Paused',
      icon: <Clock className="h-3 w-3 text-gray-600" />,
      dotColor: 'bg-gray-400'
    },
    ready: {
      label: 'Ready',
      icon: <CheckCircle className="h-3 w-3 text-emerald-600" />,
      dotColor: 'bg-emerald-400'
    },
    error: {
      label: 'Error',
      icon: <AlertCircle className="h-3 w-3 text-rose-600" />,
      dotColor: 'bg-rose-400'
    }
  };

  const statusConfig = config[status];

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
        className
      )}
    >
      {showDot && (
        <span
          className={cn('w-2 h-2 rounded-full', statusConfig.dotColor)}
          aria-hidden="true"
        />
      )}
      {statusConfig.icon}
      <span>{statusConfig.label}</span>
    </span>
  );
}
