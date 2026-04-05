'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle, Circle, Loader2, Zap, Brain, GitBranch, Users } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ProgressStep {
  step: string;
  phase: string;
  message?: string;
  status: 'complete' | 'active' | 'pending';
}

interface ProgressStepsProps {
  steps: ProgressStep[];
  title?: string;
  variant?: 'default' | 'ingest';
  className?: string;
  defaultCollapsed?: boolean;
  intent?: string;  // Detected intent to display
}

const variantStyles = {
  default: {
    container: 'bg-muted/50 border-border',
    header: 'text-foreground',
    icon: 'text-muted-foreground',
    activeStep: 'text-primary',
    completeStep: 'text-green-600 dark:text-green-400',
    pendingStep: 'text-muted-foreground/50',
  },
  ingest: {
    container: 'bg-emerald-50/80 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800/50',
    header: 'text-emerald-700 dark:text-emerald-300',
    icon: 'text-emerald-500 dark:text-emerald-400',
    activeStep: 'text-emerald-600 dark:text-emerald-400',
    completeStep: 'text-green-600 dark:text-green-400',
    pendingStep: 'text-muted-foreground/50',
  },
};

export function ProgressSteps({
  steps,
  title = 'Progress',
  variant = 'default',
  className,
  defaultCollapsed = false,
  intent,
}: ProgressStepsProps) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const styles = variantStyles[variant];

  const completedCount = steps.filter((s) => s.status === 'complete').length;
  const activeStep = steps.find((s) => s.status === 'active');
  const totalSteps = steps.length;

  const getStepIcon = (status: ProgressStep['status']) => {
    switch (status) {
      case 'complete':
        return <CheckCircle className="h-4 w-4" />;
      case 'active':
        return <Loader2 className="h-4 w-4 animate-spin" />;
      case 'pending':
        return <Circle className="h-4 w-4" />;
    }
  };

  // Intent icon mapping
  const getIntentIcon = (intentName: string) => {
    switch (intentName) {
      case 'ask_code':
        return <Zap className="h-3.5 w-3.5" />;
      case 'deep_analysis':
        return <Brain className="h-3.5 w-3.5" />;
      case 'ingest_repo':
        return <GitBranch className="h-3.5 w-3.5" />;
      case 'multi_agent':
        return <Users className="h-3.5 w-3.5" />;
      default:
        return null;
    }
  };

  const intentIcon = intent ? getIntentIcon(intent) : null;

  return (
    <div className={cn('rounded-xl border shadow-sm overflow-hidden', styles.container, className)}>
      {/* Header - always visible */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isCollapsed ? (
            <ChevronRight className={cn('h-4 w-4', styles.icon)} />
          ) : (
            <ChevronDown className={cn('h-4 w-4', styles.icon)} />
          )}
          {intentIcon && (
            <span className={cn('flex items-center', styles.icon)}>
              {intentIcon}
            </span>
          )}
          <span className={cn('text-sm font-medium', styles.header)}>{title}</span>
          <span className="text-xs text-muted-foreground">
            {completedCount}/{totalSteps}
          </span>
        </div>
        {activeStep && (
          <span className="text-xs text-muted-foreground truncate max-w-[200px]">
            {activeStep.phase}
          </span>
        )}
      </button>

      {/* Steps - collapsible */}
      {!isCollapsed && (
        <div className="px-4 pb-4 space-y-2">
          {steps.map((step, index) => (
            <div
              key={step.step}
              className={cn(
                'flex items-start gap-3 py-2 px-3 rounded-lg transition-colors',
                step.status === 'active' && 'bg-primary/5 dark:bg-primary/20',
                step.status === 'pending' && 'opacity-40'
              )}
            >
              <div
                className={cn(
                  'flex-shrink-0 mt-0.5',
                  step.status === 'complete' && styles.completeStep,
                  step.status === 'active' && styles.activeStep,
                  step.status === 'pending' && styles.pendingStep
                )}
              >
                {getStepIcon(step.status)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground font-medium">Step {index + 1}</span>
                  <span
                    className={cn(
                      'text-sm',
                      step.status === 'active' ? 'font-semibold text-foreground' : 'font-medium text-foreground/80'
                    )}
                  >
                    {step.phase}
                  </span>
                </div>
                {step.status === 'active' && step.message && (
                  <p className="text-xs text-muted-foreground mt-1 truncate max-w-md">
                    {step.message}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Helper to strip progress step lines from content
export function stripProgressSteps(content: string): string {
  const lines = content.split('\n');
  const filteredLines = lines.filter(line => !/^([✅⏳⬜])\s*Step\s*\d+\/\d+:/.test(line));
  return filteredLines.join('\n').trim();
}

// Helper to parse progress content from markdown and extract steps
export function parseProgressSteps(content: string): ProgressStep[] | null {
  // Try to parse the emoji-based progress format
  // Format: ✅ Step 1/8: Analyzing question or ⏳ Step 2/8: ...
  const lines = content.split('\n');
  const steps: ProgressStep[] = [];

  for (const line of lines) {
    const match = line.match(/^([✅⏳⬜])\s*Step\s*(\d+)\/(\d+):\s*(.+)/);
    if (match) {
      const [, emoji, , , phase] = match;
      let status: ProgressStep['status'] = 'pending';
      if (emoji === '✅') status = 'complete';
      else if (emoji === '⏳') status = 'active';

      // Extract message if present (after " - ")
      const [phaseText, message] = phase.split(' - ');
      steps.push({
        step: phaseText.trim().toLowerCase().replace(/\s+/g, '_'),
        phase: phaseText.trim(),
        message: message?.trim(),
        status,
      });
    }
  }

  return steps.length > 0 ? steps : null;
}
