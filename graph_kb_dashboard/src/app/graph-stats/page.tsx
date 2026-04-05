'use client';

import { useState, useEffect } from 'react';
import { Activity, GitBranch, Layers, TrendingUp, Database, FileCode, ArrowUpDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getGraphStats } from '@/lib/api/analysis';
import { apiClient } from '@/lib/api/client';
import type { GraphStats as ApiGraphStats } from '@/lib/types/api';

interface GraphStats {
  totalNodes: number;
  totalEdges: number;
  avgDepth: number;
  maxDepth: number;
  nodeTypes: { type: string; count: number }[];
  edgeTypes: { type: string; count: number }[];
  repositories: { name: string; nodes: number; edges: number }[];
}

interface MetricCardProps {
  title: string;
  value: string | number;
  description: string;
  icon: React.ReactNode;
  trend?: 'up' | 'down' | 'neutral';
}

function MetricCard({ title, value, description, icon, trend }: MetricCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p className="text-xs text-muted-foreground flex items-center gap-1">
          {trend && (
            <TrendingUp className={`h-3 w-3 ${trend === 'up' ? 'text-green-500' : trend === 'down' ? 'text-red-500' : ''}`} />
          )}
          {description}
        </p>
      </CardContent>
    </Card>
  );
}

export default function GraphStatsPage() {
  const [repositories, setRepositories] = useState<string[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('');
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadRepositories();
  }, []);

  useEffect(() => {
    if (selectedRepo) {
      loadStats();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRepo]);

  const loadRepositories = async () => {
    try {
      const data = await apiClient.get<{ repos: { id: string }[] }>('/repos');
      const repoIds = (data.repos || []).map((r: { id: string }) => r.id);
      setRepositories(repoIds);
      if (repoIds.length > 0) {
        setSelectedRepo(repoIds[0]);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load repositories';
      setError(errorMessage);
      console.error('Failed to load repositories:', error);
    }
  };

  const loadStats = async () => {
    if (!selectedRepo) return;
    setIsLoading(true);
    setError(null);
    try {
      const apiStats = await getGraphStats({ repoId: selectedRepo });
      // Map API stats to UI stats
      const depthAnalysis = apiStats.depth_analysis || {};
      const maxDepth = Math.max(0, ...Object.values(depthAnalysis).map(Math.abs));
      const depthValues = Object.values(depthAnalysis).map(Math.abs).filter(v => v > 0);
      const avgDepth = depthValues.length > 0 ? depthValues.reduce((a, b) => a + b, 0) / depthValues.length : 0;

      const mappedStats: GraphStats = {
        totalNodes: apiStats.total_nodes,
        totalEdges: apiStats.total_edges,
        avgDepth,
        maxDepth,
        nodeTypes: Object.entries(apiStats.node_counts).map(([type, count]) => ({ type, count })),
        edgeTypes: Object.entries(apiStats.edge_counts).map(([type, count]) => ({ type, count })),
        repositories: [{ name: selectedRepo, nodes: apiStats.total_nodes, edges: apiStats.total_edges }],
      };
      setStats(mappedStats);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load graph stats';
      setError(errorMessage);
      console.error('Failed to load graph stats:', error);
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="container mx-auto py-6">
        <div className="text-center text-muted-foreground py-12">Loading statistics...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Graph Statistics</h1>
          <p className="text-muted-foreground">Knowledge graph metrics and analytics</p>
        </div>
        <Card className="border-red-200 bg-red-50 dark:bg-red-900/10">
          <CardContent className="py-12 text-center text-red-600 dark:text-red-400">
            <p className="font-medium">Error loading statistics</p>
            <p className="text-sm mt-2">{error}</p>
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => {
                setError(null);
                loadRepositories();
              }}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Graph Statistics</h1>
          <p className="text-muted-foreground">Knowledge graph metrics and analytics</p>
        </div>
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Database className="h-16 w-16 mx-auto mb-4 opacity-50" />
            <p>No statistics available</p>
            <p className="text-sm">Ingest repositories to populate the knowledge graph</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Graph Statistics</h1>
          <p className="text-muted-foreground">Knowledge graph metrics and analytics</p>
        </div>
        <select
          value={selectedRepo}
          onChange={(e) => setSelectedRepo(e.target.value)}
          className="px-4 py-2 border rounded-md bg-background"
        >
          <option value="">Select Repository</option>
          {repositories.map(repo => (
            <option key={repo} value={repo}>{repo}</option>
          ))}
        </select>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Total Nodes"
          value={stats.totalNodes.toLocaleString()}
          description="Entities in graph"
          icon={<FileCode className="h-4 w-4 text-muted-foreground" />}
        />
        <MetricCard
          title="Total Edges"
          value={stats.totalEdges.toLocaleString()}
          description="Relationships"
          icon={<GitBranch className="h-4 w-4 text-muted-foreground" />}
        />
        <MetricCard
          title="Avg Depth"
          value={stats.avgDepth.toFixed(2)}
          description="Average call depth"
          icon={<Layers className="h-4 w-4 text-muted-foreground" />}
        />
        <MetricCard
          title="Max Depth"
          value={stats.maxDepth}
          description="Maximum call depth"
          icon={<ArrowUpDown className="h-4 w-4 text-muted-foreground" />}
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Node Types</CardTitle>
            <CardDescription>Distribution of node types in the graph</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats.nodeTypes.map(({ type, count }) => (
                <div key={type} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{type}</Badge>
                  </div>
                  <span className="font-mono text-sm">{count.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Edge Types</CardTitle>
            <CardDescription>Distribution of relationship types</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats.edgeTypes.map(({ type, count }) => (
                <div key={type} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{type}</Badge>
                  </div>
                  <span className="font-mono text-sm">{count.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Repository Breakdown</CardTitle>
          <CardDescription>Nodes and edges per repository</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {stats.repositories.map((repo) => (
              <div key={repo.name} className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                <span className="font-medium">{repo.name}</span>
                <div className="flex gap-4">
                  <span className="text-sm text-muted-foreground">
                    {repo.nodes.toLocaleString()} nodes
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {repo.edges.toLocaleString()} edges
                  </span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
