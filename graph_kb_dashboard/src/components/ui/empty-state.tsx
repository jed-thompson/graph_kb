'use client';

import * as React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  /** Icon to display (pass Lucide icon component) */
  icon: LucideIcon;
  /** Main title text */
  title: string;
  /** Optional description text */
  description?: string;
  /** Optional className for custom styling */
  className?: string;
  /** Optional children for additional content (e.g., action buttons) */
  children?: React.ReactNode;
}

/**
 * A consistent empty state component for displaying when there's no data.
 *
 * @example
 * ```tsx
 * <EmptyState
 *   icon={Folder}
 *   title="No documents found"
 *   description="Upload documents to get started"
 * />
 * ```
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  className,
  children,
}: EmptyStateProps) {
  return (
    <Card className={className}>
      <CardContent className="py-8 text-center text-muted-foreground">
        <Icon className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>{title}</p>
        {description && <p className="text-sm mt-2">{description}</p>}
        {children && <div className="mt-4">{children}</div>}
      </CardContent>
    </Card>
  );
}

export default EmptyState;
