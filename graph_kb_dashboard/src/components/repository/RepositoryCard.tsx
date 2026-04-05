'use client';

import Link from 'next/link';
import type { Repository } from '@/lib/types/api';
import { StatusBadge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  GitBranch,
  Calendar,
  ExternalLink,
  Trash2
} from 'lucide-react';
import { cn } from '@/lib/utils';

export interface RepositoryCardProps {
  repository: Repository;
  onDelete?: (repoId: string) => void;
  showDelete?: boolean;
}

export function RepositoryCard({ repository, onDelete, showDelete = false }: RepositoryCardProps) {
  return (
    <div className="group relative overflow-hidden rounded-xl border border-border/50 bg-card hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5/10 transition-all duration-300 ease-out">
      {/* Gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-r from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />

      <div className="relative px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          {/* Left side - Repository info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <Link
                href={`/repositories/${repository.id}`}
                className="text-lg font-semibold text-foreground hover:text-primary transition-colors duration-200"
              >
                {repository.id}
              </Link>
              <StatusBadge status={repository.status} />
            </div>

            <p className="text-sm text-muted-foreground break-all mb-3 flex items-center gap-2">
              <ExternalLink className="h-4 w-4 flex-shrink-0" />
              <span className="truncate">{repository.git_url}</span>
            </p>

            <div className="flex items-center gap-4 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <GitBranch className="h-3.5 w-3.5" />
                <span>{repository.branch}</span>
              </span>
              {repository.last_indexed_at && (
                <span className="inline-flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5" />
                  <span>
                    Indexed {new Date(repository.last_indexed_at).toLocaleDateString()}
                  </span>
                </span>
              )}
            </div>
          </div>

          {/* Right side - Actions */}
          <div className="flex items-center gap-2">
            <Link
              href={`/repositories/${repository.id}`}
              className="inline-flex items-center justify-center px-3 py-2 rounded-lg text-sm font-medium text-primary hover:bg-primary/10 transition-colors duration-200"
            >
              View Details
            </Link>
            {showDelete && onDelete && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onDelete(repository.id)}
                className="text-destructive hover:text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
