'use client';

import { useEffect, useState, useCallback } from 'react';
import type { Repository, GraphStats, Hotspot, EntryPoint } from '@/lib/types/api';
import { getRepository } from '@/lib/api/repositories';
import { getGraphStats } from '@/lib/api/analysis';
import { getHotspots } from '@/lib/api/analysis';
import { getEntryPoints } from '@/lib/api/analysis';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingCard } from '@/components/ui/Loading';
import { Card, CardHeader, CardContent } from '@/components/ui/card';

interface RepositoryDetailProps {
  repoId: string;
}

export function RepositoryDetail({ repoId }: RepositoryDetailProps) {
  const [repository, setRepository] = useState<Repository | null>(null);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [entryPoints, setEntryPoints] = useState<EntryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadRepositoryDetails = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [repo, statsData, hotspotsData, entryPointsData] = await Promise.all([
        getRepository(repoId),
        getGraphStats({ repoId }),
        getHotspots({ repoId, limit: 10 }),
        getEntryPoints({ repoId, limit: 10 }),
      ]);

      setRepository(repo);
      setStats(statsData);
      setHotspots(hotspotsData);
      setEntryPoints(entryPointsData);
    } catch (err) {
      setError('Failed to load repository details');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [repoId]);

  useEffect(() => {
    loadRepositoryDetails();
  }, [loadRepositoryDetails]);

  if (loading) return <LoadingCard />;

  if (error || !repository) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
        <p className="text-red-800">{error || 'Repository not found'}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Repository Info */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{repository.id}</h2>
            <Badge variant="secondary">{repository.status}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div>
              <p className="text-sm text-gray-500">Git URL</p>
              <p className="text-gray-900 break-all">{repository.git_url}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Branch</p>
              <p className="text-gray-900">{repository.branch}</p>
            </div>
            {repository.last_indexed_at && (
              <div>
                <p className="text-sm text-gray-500">Last Indexed</p>
                <p className="text-gray-900">
                  {new Date(repository.last_indexed_at).toLocaleString()}
                </p>
              </div>
            )}
            {repository.commit_sha && (
              <div>
                <p className="text-sm text-gray-500">Commit</p>
                <p className="text-gray-900 font-mono text-sm">
                  {repository.commit_sha.substring(0, 7)}
                </p>
              </div>
            )}
            {repository.error_message && (
              <div className="text-red-600">
                <p className="text-sm">Error</p>
                <p>{repository.error_message}</p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Graph Statistics */}
      {stats && (
        <Card>
          <CardHeader>
            <h2 className="text-lg font-semibold">Graph Statistics</h2>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatItem label="Total Nodes" value={stats.total_nodes} />
              <StatItem label="Total Edges" value={stats.total_edges} />
              <StatItem label="Functions" value={stats.node_counts['function'] || 0} />
              <StatItem label="Classes" value={stats.node_counts['class'] || 0} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Hotspots */}
      {hotspots.length > 0 && (
        <Card>
          <CardHeader>
            <h2 className="text-lg font-semibold">Code Hotspots</h2>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {hotspots.map((hotspot, index) => (
                <div key={index} className="p-3 bg-gray-50 rounded-lg">
                  <p className="font-medium text-gray-900">{hotspot.symbol_name}</p>
                  <p className="text-sm text-gray-600 break-all">{hotspot.file_path}</p>
                  <div className="mt-2 flex gap-4 text-sm">
                    <span>Complexity: {hotspot.complexity}</span>
                    <span>Incoming: {hotspot.incoming_calls}</span>
                    <span>Outgoing: {hotspot.outgoing_calls}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Entry Points */}
      {entryPoints.length > 0 && (
        <Card>
          <CardHeader>
            <h2 className="text-lg font-semibold">Entry Points</h2>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {entryPoints.map((entry, index) => (
                <div key={index} className="flex items-center justify-between p-3 border border-gray-200 rounded-lg">
                  <div>
                    <p className="font-medium text-gray-900">{entry.name}</p>
                    <p className="text-sm text-gray-600 break-all">{entry.file_path}</p>
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">
                      {entry.type}
                    </span>
                  </div>
                  {entry.score != null && (
                    <span className="text-gray-500">
                      Relevance: {(entry.score * 100).toFixed(1)}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatItem({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-semibold text-gray-900">{value}</p>
    </div>
  );
}
