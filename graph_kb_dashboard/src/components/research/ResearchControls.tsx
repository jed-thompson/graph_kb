'use client';

import { useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { GitBranch, Search, Loader2, FolderGit2 } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import { WebUrlInput } from './WebUrlInput';
import { DocumentUploader } from './DocumentUploader';

interface ResearchControlsProps {
  repositories: Array<{ id: string; name: string; status: string }>;
  onStartResearch: () => void;
}

/**
 * ResearchControls - Container with repository selector, URL input, file upload.
 * Manages all research input controls.
 */
export function ResearchControls({ repositories, onStartResearch }: ResearchControlsProps) {
  const {
    selectedRepoId,
    setSelectedRepoId,
    webUrls,
    uploadedDocuments,
    status,
    progress,
  } = useResearchStore();

  const isResearching = status === 'running' || status === 'reviewing';
  const progressPercent = Math.round(progress.percent * 100);

  const handleStartResearch = useCallback(() => {
    if (!selectedRepoId) return;
    onStartResearch();
  }, [selectedRepoId, onStartResearch]);

  const canStartResearch = selectedRepoId && !isResearching;

  const readyRepos = repositories.filter((r) => r.status === 'ready');

  return (
    <Card className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        <Search className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Research Configuration</h2>
      </div>

      {/* Repository Selector */}
      <div className="space-y-2">
        <label className="text-sm font-medium flex items-center gap-2">
          <FolderGit2 className="h-4 w-4" />
          Target Repository
        </label>
        <Select
          value={selectedRepoId || ''}
          onValueChange={setSelectedRepoId}
          disabled={isResearching}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select a repository to research" />
          </SelectTrigger>
          <SelectContent>
            {readyRepos.length === 0 ? (
              <SelectItem value="_none" disabled>
                No repositories available
              </SelectItem>
            ) : (
              readyRepos.map((repo) => (
                <SelectItem key={repo.id} value={repo.id}>
                  <div className="flex items-center gap-2">
                    <GitBranch className="h-4 w-4" />
                    <span>{repo.name}</span>
                  </div>
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      </div>

      <Separator />

      {/* Web URL Input */}
      <WebUrlInput disabled={isResearching} />

      <Separator />

      {/* Document Upload */}
      <DocumentUploader disabled={isResearching} />

      {/* Context Summary */}
      {(webUrls.length > 0 || uploadedDocuments.length > 0) && (
        <div className="bg-muted/50 rounded-lg p-3 text-sm">
          <p className="font-medium mb-1">Context Sources:</p>
          <ul className="text-muted-foreground space-y-0.5">
            <li>• {webUrls.length} web URL{webUrls.length !== 1 ? 's' : ''}</li>
            <li>• {uploadedDocuments.length} document{uploadedDocuments.length !== 1 ? 's' : ''}</li>
          </ul>
        </div>
      )}

      {/* Start Button */}
      <Button
        onClick={handleStartResearch}
        disabled={!canStartResearch}
        className="w-full"
        size="lg"
      >
        {isResearching ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Researching... {progressPercent}%
          </>
        ) : (
          <>
            <Search className="h-4 w-4 mr-2" />
            Start Research
          </>
        )}
      </Button>

      {!selectedRepoId && (
        <p className="text-xs text-muted-foreground text-center">
          Select a repository to begin research
        </p>
      )}
    </Card>
  );
}

export default ResearchControls;
