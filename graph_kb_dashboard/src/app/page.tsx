// Dashboard home page

'use client';

import { useEffect, useState } from 'react';
import { listRepositories } from '@/lib/api/repositories';
import type { Repository, RepoStatus } from '@/lib/types/api';

export default function DashboardPage() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadRepositories();
  }, []);

  const loadRepositories = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await listRepositories({ limit: 10 });
      setRepositories(response.repos);
    } catch (err) {
      setError('Failed to load repositories');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">GraphKB Dashboard</h1>
          <p className="text-gray-600 mt-2">
            Manage your code knowledge graphs and explore your repositories
          </p>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <StatCard title="Total Repositories" value={repositories.length} color="blue" />
          <StatCard title="Ready" value={repositories.filter((r) => r.status === 'ready').length} color="green" />
          <StatCard title="Indexing" value={repositories.filter((r) => r.status === 'indexing').length} color="yellow" />
          <StatCard title="Errors" value={repositories.filter((r) => r.status === 'error').length} color="red" />
        </div>

        {/* Repository List */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold">Recent Repositories</h2>
          </div>
          <div className="divide-y divide-gray-200">
            {loading ? (
              <div className="px-6 py-8 text-center text-gray-500">Loading...</div>
            ) : error ? (
              <div className="px-6 py-8 text-center text-red-500">{error}</div>
            ) : repositories.length === 0 ? (
              <div className="px-6 py-8 text-center text-gray-500">
                No repositories found. Go to{' '}
                <a href="/repositories" className="text-blue-600 hover:underline">
                  Repositories
                </a>{' '}
                to add one.
              </div>
            ) : (
              repositories.map((repo) => (
                <RepositoryItem key={repo.id} repository={repo} />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ title, value, color }: { title: string; value: number; color: string }) {
  const colorClasses: Record<string, string> = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    red: 'bg-red-500',
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className={`inline-flex items-center justify-center w-12 h-12 rounded-lg ${colorClasses[color]} mb-4`}>
        <span className="text-white text-xl font-bold">{value}</span>
      </div>
      <h3 className="text-sm font-medium text-gray-500 uppercase">{title}</h3>
    </div>
  );
}

function RepositoryItem({ repository }: { repository: Repository }) {
  const statusColors: Record<RepoStatus, string> = {
    ready: 'bg-green-100 text-green-800',
    indexing: 'bg-yellow-100 text-yellow-800',
    cloning: 'bg-blue-100 text-blue-800',
    paused: 'bg-gray-100 text-gray-800',
    error: 'bg-red-100 text-red-800',
    pending: 'bg-gray-100 text-gray-800',
  };

  return (
    <div className="px-6 py-4 hover:bg-gray-50 transition-colors">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-gray-900">{repository.id}</h3>
          <p className="text-sm text-gray-500 mt-1">{repository.git_url}</p>
        </div>
        <span
          className={`px-2 py-1 text-xs font-medium rounded-full ${statusColors[repository.status]}`}
        >
          {repository.status}
        </span>
      </div>
    </div>
  );
}
