'use client';

import { Card } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Check, Clock, Loader2, AlertCircle } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import { cn } from '@/lib/utils';

/**
 * ResearchProgressIndicator - Progress bar and thinking steps display.
 * Reuses patterns from ThinkingStepsPanel in plan components.
 */
export function ResearchProgressIndicator() {
  const { status, progress } = useResearchStore();
  const { percent, phase, message, steps } = progress;

  const isActive = status === 'running' || status === 'reviewing';
  const isComplete = status === 'complete';
  const isError = status === 'error';

  const progressPercent = Math.round(percent * 100);

  const getStatusIcon = () => {
    if (isError) return <AlertCircle className="h-5 w-5 text-red-500" />;
    if (isComplete) return <Check className="h-5 w-5 text-green-500" />;
    if (isActive) return <Loader2 className="h-5 w-5 text-primary animate-spin" />;
    return <Clock className="h-5 w-5 text-muted-foreground" />;
  };

  const getStatusColor = () => {
    if (isError) return 'text-red-500';
    if (isComplete) return 'text-green-500';
    if (isActive) return 'text-primary';
    return 'text-muted-foreground';
  };

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  return (
    <Card className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Research Progress</h3>
        <div className={cn('flex items-center gap-2', getStatusColor())}>
          {getStatusIcon()}
          <span className="text-sm capitalize">{status}</span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground capitalize">{phase} Phase</span>
          <span className="font-medium">{progressPercent}%</span>
        </div>
        <Progress value={progressPercent} className="h-2" />
      </div>

      {/* Current Message */}
      {message && (
        <p className="text-sm text-muted-foreground bg-muted/50 rounded-md p-3">
          {message}
        </p>
      )}

      {/* Thinking Steps */}
      {steps.length > 0 && (
        <ScrollArea className="h-[200px] border rounded-md">
          <div className="p-3 space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">
              Activity Log
            </p>
            {steps.map((step, index) => (
              <div
                key={`${step.timestamp}-${index}`}
                className="flex items-start gap-3 text-sm py-1.5"
              >
                <span className="text-xs text-muted-foreground font-mono shrink-0">
                  {formatTime(step.timestamp)}
                </span>
                <span className={cn(
                  index === steps.length - 1 && isActive
                    ? 'text-foreground font-medium'
                    : 'text-muted-foreground'
                )}>
                  {step.message}
                </span>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}

      {/* Empty State */}
      {!isActive && steps.length === 0 && (
        <div className="text-center py-6 text-muted-foreground text-sm">
          <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p>No research activity yet</p>
          <p className="text-xs mt-1">Configure sources and click &quot;Start Research&quot;</p>
        </div>
      )}
    </Card>
  );
}

export default ResearchProgressIndicator;
