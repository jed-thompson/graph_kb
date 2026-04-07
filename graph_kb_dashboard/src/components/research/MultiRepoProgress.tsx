'use client';

import { useResearchStore } from '@/lib/store/researchStore';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { CheckCircle2, XCircle, Loader2, Clock } from 'lucide-react';

const STATUS_ICONS = {
  pending: <Clock className="h-4 w-4 text-muted-foreground" />,
  running: <Loader2 className="h-4 w-4 text-primary animate-spin" />,
  complete: <CheckCircle2 className="h-4 w-4 text-green-500" />,
  error: <XCircle className="h-4 w-4 text-destructive" />,
};

const STATUS_BADGE_VARIANTS = {
  pending: 'secondary',
  running: 'default',
  complete: 'default',
  error: 'destructive',
} as const;

interface MultiRepoProgressProps {
  overallProgress: number;
}

export function MultiRepoProgress({ overallProgress }: MultiRepoProgressProps) {
  const { perRepoFindings } = useResearchStore();
  const entries = Object.values(perRepoFindings);

  if (entries.length === 0) return null;

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <div className="flex justify-between text-sm">
          <span className="font-medium">Overall Progress</span>
          <span className="text-muted-foreground">{Math.round(overallProgress * 100)}%</span>
        </div>
        <Progress value={overallProgress * 100} className="h-2" />
      </div>

      <div className="grid gap-3">
        {entries.map((repo) => (
          <div key={repo.repoId} className="rounded-lg border p-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                {STATUS_ICONS[repo.status]}
                <span className="text-sm font-medium truncate">{repo.repoName}</span>
              </div>
              <Badge variant={STATUS_BADGE_VARIANTS[repo.status]} className="shrink-0 text-xs">
                {repo.status}
              </Badge>
            </div>

            {repo.status === 'running' && (
              <>
                <Progress value={repo.progress * 100} className="h-1.5" />
                <p className="text-xs text-muted-foreground">{repo.phase}</p>
              </>
            )}

            {repo.status === 'error' && (
              <div className="rounded bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
                <span className="font-medium">Failed in {repo.errorPhase ?? 'unknown phase'}: </span>
                {repo.errorMessage}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
