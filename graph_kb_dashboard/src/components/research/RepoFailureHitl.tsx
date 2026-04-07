'use client';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { AlertTriangle, SkipForward, RefreshCw, XOctagon } from 'lucide-react';

interface RepoFailureHitlProps {
  failedRepoId: string;
  errorMessage: string;
  phase: string;
  onContinue: () => void;
  onRetry: () => void;
  onAbort: () => void;
}

export function RepoFailureHitl({
  failedRepoId,
  errorMessage,
  phase,
  onContinue,
  onRetry,
  onAbort,
}: RepoFailureHitlProps) {
  return (
    <Dialog open>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            <DialogTitle>Repository Research Failed</DialogTitle>
          </div>
          <DialogDescription className="text-left space-y-2 pt-2">
            <p>
              <span className="font-medium">{failedRepoId}</span> failed during the{' '}
              <span className="font-mono text-xs bg-muted px-1 py-0.5 rounded">{phase}</span> phase.
            </p>
            <p className="text-destructive text-sm">{errorMessage}</p>
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2 pt-2">
          <Button onClick={onContinue} variant="outline" className="justify-start gap-2">
            <SkipForward className="h-4 w-4" />
            Continue without this repo
          </Button>
          <Button onClick={onRetry} variant="outline" className="justify-start gap-2">
            <RefreshCw className="h-4 w-4" />
            Retry this repo
          </Button>
          <Button onClick={onAbort} variant="destructive" className="justify-start gap-2">
            <XOctagon className="h-4 w-4" />
            Abort entire run
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
