'use client';

import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Zap, GitMerge } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import type { ExecutionStrategy } from '@/lib/types/research';

export function ExecutionStrategyToggle() {
  const { executionStrategy, setExecutionStrategy } = useResearchStore();

  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">Execution Strategy</label>
      <TooltipProvider>
        <div className="flex gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={executionStrategy === 'parallel_merge' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setExecutionStrategy('parallel_merge' as ExecutionStrategy)}
                className="gap-2 text-xs"
              >
                <Zap className="h-3.5 w-3.5" />
                Parallel + Merge
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>All repos researched concurrently, then findings merged</p>
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={executionStrategy === 'dependency_aware' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setExecutionStrategy('dependency_aware' as ExecutionStrategy)}
                className="gap-2 text-xs"
              >
                <GitMerge className="h-3.5 w-3.5" />
                Dependency-Aware
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>Repos run in dependency order; upstream findings inform downstream research</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </TooltipProvider>
    </div>
  );
}
