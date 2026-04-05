'use client';

import * as CollapsiblePrimitive from '@radix-ui/react-collapsible';
import { useState, ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

// Radix-based collapsible primitives
const Collapsible = CollapsiblePrimitive.Root;
const CollapsibleTrigger = CollapsiblePrimitive.CollapsibleTrigger;
const CollapsibleContent = CollapsiblePrimitive.CollapsibleContent;

// Higher-level CollapsibleSection component
interface CollapsibleSectionProps {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  variant?: 'default' | 'violet' | 'emerald' | 'amber' | 'sky';
  badge?: ReactNode;
  icon?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
}

const variantStyles = {
  default: {
    header: 'bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800',
    border: 'border-gray-200 dark:border-gray-700',
    title: 'text-gray-900 dark:text-gray-100',
    chevron: 'text-gray-500 dark:text-gray-400',
  },
  violet: {
    header: 'bg-violet-50 dark:bg-violet-950/30 hover:bg-violet-100 dark:hover:bg-violet-950/50',
    border: 'border-violet-200 dark:border-violet-800',
    title: 'text-violet-900 dark:text-violet-100',
    chevron: 'text-violet-500 dark:text-violet-400',
  },
  emerald: {
    header: 'bg-emerald-50 dark:bg-emerald-950/30 hover:bg-emerald-100 dark:hover:bg-emerald-950/50',
    border: 'border-emerald-200 dark:border-emerald-800',
    title: 'text-emerald-900 dark:text-emerald-100',
    chevron: 'text-emerald-500 dark:text-emerald-400',
  },
  amber: {
    header: 'bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-950/50',
    border: 'border-amber-200 dark:border-amber-800',
    title: 'text-amber-900 dark:text-amber-100',
    chevron: 'text-amber-500 dark:text-amber-400',
  },
  sky: {
    header: 'bg-sky-50 dark:bg-sky-950/30 hover:bg-sky-100 dark:hover:bg-sky-950/50',
    border: 'border-sky-200 dark:border-sky-800',
    title: 'text-sky-900 dark:text-sky-100',
    chevron: 'text-sky-500 dark:text-sky-400',
  },
};

const sizeStyles = {
  sm: {
    container: 'rounded-lg',
    header: 'px-3 py-2',
    content: 'p-3',
    title: 'text-sm font-semibold',
    chevron: 'w-4 h-4',
  },
  md: {
    container: 'rounded-xl',
    header: 'px-4 py-3',
    content: 'p-4',
    title: 'text-base font-bold',
    chevron: 'w-5 h-5',
  },
  lg: {
    container: 'rounded-2xl',
    header: 'px-5 py-4',
    content: 'p-5',
    title: 'text-lg font-bold',
    chevron: 'w-5 h-5',
  },
};

function CollapsibleSection({
  title,
  children,
  defaultOpen = false,
  className,
  variant = 'default',
  badge,
  icon,
  size = 'md',
}: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const vStyles = variantStyles[variant];
  const sStyles = sizeStyles[size];

  return (
    <div className={cn('border overflow-hidden transition-all duration-200', vStyles.border, sStyles.container, className)}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'w-full flex items-center gap-3 transition-colors text-left',
          vStyles.header,
          sStyles.header
        )}
      >
        <span className="flex-shrink-0 transition-transform duration-200" style={{ transform: isOpen ? 'rotate(0deg)' : 'rotate(-90deg)' }}>
          <ChevronDown className={cn(vStyles.chevron, sStyles.chevron)} />
        </span>
        {icon && <span className="flex-shrink-0">{icon}</span>}
        <span className={cn('flex-1 truncate', vStyles.title, sStyles.title)}>{title}</span>
        {badge && <span className="flex-shrink-0">{badge}</span>}
      </button>
      <div
        className={cn(
          'grid transition-[grid-template-rows,opacity] duration-300 ease-in-out',
          isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        )}
      >
        <div className={cn('border-t overflow-hidden', vStyles.border)}>
          <div className={sStyles.content}>{children}</div>
        </div>
      </div>
    </div>
  );
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent, CollapsibleSection };
