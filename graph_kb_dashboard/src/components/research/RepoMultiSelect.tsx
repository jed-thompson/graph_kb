'use client';

import { Switch } from '@/components/ui/switch';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { GitBranch } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';

interface Repo {
  id: string;
  name: string;
  status: string;
}

interface RepoMultiSelectProps {
  repositories: Repo[];
  disabled?: boolean;
}

export function RepoMultiSelect({ repositories, disabled = false }: RepoMultiSelectProps) {
  const { selectedRepoIds, toggleRepoSelection } = useResearchStore();
  const readyRepos = repositories.filter((r) => r.status === 'ready');
  const atCap = selectedRepoIds.length >= 5;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">
          {selectedRepoIds.length > 0
            ? `${selectedRepoIds.length} selected`
            : 'Select repositories'}
        </span>
        {atCap && (
          <span className="text-xs text-muted-foreground">Maximum 5 repositories</span>
        )}
      </div>
      {readyRepos.length === 0 ? (
        <p className="text-sm text-muted-foreground">No ready repositories available</p>
      ) : (
        <div className="space-y-1">
          {readyRepos.map((repo) => {
            const isChecked = selectedRepoIds.includes(repo.id);
            const isDisabled = disabled || (!isChecked && atCap);

            const row = (
              <div
                key={repo.id}
                className={`flex items-center gap-2 p-2 rounded-md hover:bg-muted/50 ${isDisabled && !isChecked ? 'opacity-50' : ''}`}
              >
                <Switch
                  id={`repo-${repo.id}`}
                  checked={isChecked}
                  disabled={isDisabled}
                  onCheckedChange={() => !isDisabled && toggleRepoSelection(repo.id)}
                />
                <label
                  htmlFor={`repo-${repo.id}`}
                  className={`flex items-center gap-2 text-sm flex-1 ${isDisabled && !isChecked ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                >
                  <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                  {repo.name}
                </label>
              </div>
            );

            if (!isChecked && atCap) {
              return (
                <TooltipProvider key={repo.id}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div>{row}</div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Maximum 5 repositories per research run</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              );
            }
            return row;
          })}
        </div>
      )}
    </div>
  );
}
