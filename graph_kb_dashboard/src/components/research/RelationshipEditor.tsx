'use client';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { X, Plus, GitFork } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';
import { useRelationshipEditor } from '@/hooks/useRelationshipEditor';
import type { RelationshipType } from '@/lib/types/research';

interface Repo {
  id: string;
  name: string;
}

interface RelationshipEditorProps {
  repositories: Repo[];
}

const RELATIONSHIP_LABELS: Record<RelationshipType, string> = {
  dependency: 'Dependency',
  rest: 'REST',
  grpc: 'gRPC',
};

export function RelationshipEditor({ repositories }: RelationshipEditorProps) {
  const { selectedRepoIds } = useResearchStore();
  const {
    relationships,
    removeRelationship,
    sourceId,
    setSourceId,
    targetId,
    setTargetId,
    relType,
    setRelType,
    handleAdd,
  } = useRelationshipEditor();

  const selectedRepos = repositories.filter((r) => selectedRepoIds.includes(r.id));

  const getRepoName = (id: string) => repositories.find((r) => r.id === id)?.name ?? id;

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <GitFork className="h-4 w-4" />
          Define Relationships
          {relationships.length > 0 && (
            <Badge variant="secondary" className="ml-1">{relationships.length}</Badge>
          )}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Define Repository Relationships</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-end">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Source</label>
              <Select value={sourceId} onValueChange={setSourceId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select repo" />
                </SelectTrigger>
                <SelectContent>
                  {selectedRepos.map((r) => (
                    <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Type</label>
              <Select value={relType} onValueChange={(v) => setRelType(v as RelationshipType)}>
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="dependency">Dependency</SelectItem>
                  <SelectItem value="rest">REST</SelectItem>
                  <SelectItem value="grpc">gRPC</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Target</label>
              <Select value={targetId} onValueChange={setTargetId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select repo" />
                </SelectTrigger>
                <SelectContent>
                  {selectedRepos
                    .filter((r) => r.id !== sourceId)
                    .map((r) => (
                      <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <Button
            onClick={handleAdd}
            disabled={!sourceId || !targetId || sourceId === targetId}
            size="sm"
            className="w-full gap-2"
          >
            <Plus className="h-4 w-4" />
            Add Relationship
          </Button>

          {relationships.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Defined relationships</p>
              {relationships.map((rel) => (
                <div
                  key={rel.id}
                  className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                >
                  <span className="flex items-center gap-2">
                    <span className="font-medium">{getRepoName(rel.sourceRepoId)}</span>
                    <Badge variant="outline" className="text-xs">{RELATIONSHIP_LABELS[rel.relationshipType]}</Badge>
                    <span>→</span>
                    <span className="font-medium">{getRepoName(rel.targetRepoId)}</span>
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => removeRelationship(rel.id)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
