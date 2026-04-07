'use client';

import { Separator } from '@/components/ui/separator';
import { FolderGit2 } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import { WebUrlInput } from './WebUrlInput';
import { DocumentUploader } from './DocumentUploader';
import { RepoMultiSelect } from './RepoMultiSelect';
import { RelationshipEditor } from './RelationshipEditor';
import { ExecutionStrategyToggle } from './ExecutionStrategyToggle';

interface ResearchControlsProps {
  repositories: Array<{ id: string; name: string; status: string }>;
}

/**
 * ResearchControls — multi-repo targeting configuration.
 *
 * The user selects repositories, defines relationships, and sets the execution
 * strategy here. When they send a message in the chat, those repos are used
 * transparently as context — no separate "Start Research" step needed.
 */
export function ResearchControls({ repositories }: ResearchControlsProps) {
  const { selectedRepoIds, webUrls, uploadedDocuments } = useResearchStore();

  return (
    <div className="p-4 space-y-5">
      {/* Repository Selector */}
      <div className="space-y-2">
        <label className="text-sm font-medium flex items-center gap-2">
          <FolderGit2 className="h-4 w-4" />
          Target Repositories
        </label>
        <RepoMultiSelect repositories={repositories} disabled={false} />
        {selectedRepoIds.length >= 2 && (
          <div className="space-y-3 pt-1">
            <RelationshipEditor repositories={repositories} />
            <ExecutionStrategyToggle />
          </div>
        )}
      </div>

      <Separator />

      <WebUrlInput disabled={false} />

      <Separator />

      <DocumentUploader disabled={false} />

      {(webUrls.length > 0 || uploadedDocuments.length > 0) && (
        <div className="bg-muted/50 rounded-lg p-3 text-sm">
          <p className="font-medium mb-1">Context Sources:</p>
          <ul className="text-muted-foreground space-y-0.5">
            <li>• {webUrls.length} web URL{webUrls.length !== 1 ? 's' : ''}</li>
            <li>• {uploadedDocuments.length} document{uploadedDocuments.length !== 1 ? 's' : ''}</li>
          </ul>
        </div>
      )}

      <p className="text-xs text-muted-foreground text-center pt-1">
        {selectedRepoIds.length === 0
          ? 'Select repositories to add them as context for your questions.'
          : selectedRepoIds.length === 1
          ? 'Ask questions in the chat — this repo will be used as context.'
          : `Ask questions in the chat — all ${selectedRepoIds.length} repos will be searched.`}
      </p>
    </div>
  );
}

export default ResearchControls;
