'use client';

import { useState, useEffect, useCallback } from 'react';
import type { Repository, RepoStatus } from '@/lib/types/api';
import { RepositoryCard } from '@/components/repository/RepositoryCard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingCard, EmptyState } from '@/components/ui/Loading';
import { listRepositories, deleteRepository as deleteRepo } from '@/lib/api/repositories';
import { IngestDialog } from '@/components/repository/IngestDialog';
import { Plus } from 'lucide-react';

export function RepositoryList() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<RepoStatus | ''>('');
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [ingestOpen, setIngestOpen] = useState(false);

  // Auto-load repositories on mount
  useEffect(() => {
    loadRepositories();
  }, []);

  const loadRepositories = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await listRepositories();
      setRepositories(response.repos);
    } catch (err) {
      setError('Failed to load repositories');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (repoId: string) => {
    try {
      await deleteRepo(repoId);
      setRepositories(repos => repos.filter(r => r.id !== repoId));
      setDeleteConfirm(null);
    } catch (err) {
      setError('Failed to delete repository');
      console.error(err);
    }
  };

  // Stable callback so IngestDialog doesn't re-subscribe on every render
  const handleIngestComplete = useCallback((data: { repoId: string; url: string }) => {
    setIngestOpen(false);
    loadRepositories();
  }, []);

  const handleIngestCancel = useCallback(() => {
    setIngestOpen(false);
  }, []);

  const filteredRepositories = repositories.filter(repo => {
    const matchesSearch = !searchQuery ||
      repo.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      repo.git_url.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = !statusFilter || repo.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  if (loading) return <LoadingCard />;

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
        <p className="text-red-800">{error}</p>
        <Button onClick={loadRepositories} className="mt-4">
          Retry
        </Button>
      </div>
    );
  }

  // Render a single IngestDialog outside the conditional branches so it is
  // never unmounted/remounted when the repository list transitions between
  // empty and non-empty states.  Previously two separate IngestDialog
  // instances lived in different JSX branches, causing React to destroy one
  // and create another — killing active WebSocket subscriptions mid-ingest.
  return (
    <>
      {filteredRepositories.length === 0 ? (
        <>
          <EmptyState
            title="No repositories found"
            description={repositories.length === 0
              ? "Add a repository to get started."
              : "Try adjusting your search or filter."
            }
          />
          {repositories.length === 0 && (
            <div className="flex justify-center mt-4">
              <Button onClick={() => setIngestOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Add Repository
              </Button>
            </div>
          )}
        </>
      ) : (
        <div className="space-y-4">
          {/* Filters */}
          <div className="bg-white rounded-lg shadow-sm p-4">
            <div className="flex flex-col md:flex-row gap-4">
              <Input
                placeholder="Search repositories..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1"
              />
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as RepoStatus | '')}
                className="px-4 py-2 border border-gray-300 rounded-lg focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All Status</option>
                <option value="ready">Ready</option>
                <option value="indexing">Indexing</option>
                <option value="pending">Pending</option>
                <option value="error">Error</option>
              </select>
              <Button onClick={() => setIngestOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Add Repository
              </Button>
            </div>
          </div>

          {/* Repository List */}
          <div className="space-y-4">
            {filteredRepositories.map(repo => (
              <RepositoryCard
                key={repo.id}
                repository={repo}
                onDelete={handleDelete}
                showDelete={true}
              />
            ))}
          </div>
        </div>
      )}

      {/* Single IngestDialog instance — always in the same tree position */}
      <IngestDialog
        open={ingestOpen}
        onOpenChange={setIngestOpen}
        onIngest={handleIngestComplete}
        onCancel={handleIngestCancel}
      />
    </>
  );
}
