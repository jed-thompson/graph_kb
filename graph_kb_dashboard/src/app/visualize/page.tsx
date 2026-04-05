'use client';

import { useState, useEffect, useMemo, useRef } from 'react';
import dynamic from 'next/dynamic';
import {
  Network, GitBranch, Layers, TrendingUp, RefreshCw,
  Workflow, Flame, Link2, Globe,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import NodeDetails from '@/components/visualization/NodeDetails';
import { GraphNode, GraphEdge, VisualizationType } from '@/lib/types/api';
import { apiClient } from '@/lib/api/client';
import { getVisualization } from '@/lib/api/visualization';

const GraphCanvas = dynamic(() => import('@/components/visualization/GraphCanvas'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-muted-foreground">
      Loading visualization...
    </div>
  ),
});

const VIZ_TYPES: { type: VisualizationType; label: string; icon: React.ReactNode }[] = [
  { type: 'architecture', label: 'Architecture', icon: <Layers className="h-4 w-4" /> },
  { type: 'calls', label: 'Call Graph', icon: <GitBranch className="h-4 w-4" /> },
  { type: 'dependencies', label: 'Dependencies', icon: <Network className="h-4 w-4" /> },
  { type: 'full', label: 'Full', icon: <Globe className="h-4 w-4" /> },
  { type: 'comprehensive', label: 'Comprehensive', icon: <Workflow className="h-4 w-4" /> },
  { type: 'call_chain', label: 'Call Chain', icon: <Link2 className="h-4 w-4" /> },
  { type: 'hotspots', label: 'Hotspots', icon: <Flame className="h-4 w-4" /> },
];

export default function VisualizePage() {
  const [repositories, setRepositories] = useState<string[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('');
  const [vizType, setVizType] = useState<VisualizationType>('architecture');
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [html, setHtml] = useState<string | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [symbolInput, setSymbolInput] = useState<string>('');
  const [suggestions, setSuggestions] = useState<Array<{ name: string; kind: string; file_path: string }>>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadRepositories();
  }, []);

  useEffect(() => {
    if (selectedRepo) {
      loadVisualization();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRepo, vizType]);

  useEffect(() => {
    if (!symbolInput.trim() || !selectedRepo || vizType !== 'call_chain') {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await apiClient.get<Array<{ name: string; kind: string; file_path: string }>>(
          `/repos/${selectedRepo}/symbols?pattern=${encodeURIComponent(symbolInput)}&limit=10`
        );
        setSuggestions(Array.isArray(results) ? results : []);
        setShowSuggestions(true);
      } catch {
        setSuggestions([]);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolInput, selectedRepo, vizType]);

  const loadRepositories = async () => {
    try {
      const data = await apiClient.get<{ repos: { id: string }[] }>('/repos');
      const repoIds = (data.repos || []).map((r: { id: string }) => r.id);
      setRepositories(repoIds);
      if (repoIds.length > 0) {
        setSelectedRepo(repoIds[0]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load repositories';
      setError(msg);
    }
  };

  const loadVisualization = async () => {
    if (!selectedRepo) return;
    setIsLoading(true);
    setError(null);
    setHtml(undefined);
    setSelectedNode(null);
    try {
      const response = await getVisualization(selectedRepo, vizType, {
        symbolName: vizType === 'call_chain' ? symbolInput : undefined,
      });
      setNodes(
        response.nodes.map((n, i) => ({
          id: n.id,
          label: n.label,
          type: n.type,
          x: Math.random() * 800,
          y: Math.random() * 600,
          ...(n.file_path ? { file_path: n.file_path } : {}),
          ...(n.metadata ? { metadata: n.metadata } : {}),
        }))
      );
      setEdges(
        response.edges.map((e) => ({
          source: e.source,
          target: e.target,
          type: e.type,
          ...(e.metadata ? { metadata: e.metadata } : {}),
        }))
      );
      setHtml(response.html ?? undefined);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load visualization';
      setError(msg);
      setNodes([]);
      setEdges([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Build a blob URL for the sandboxed iframe when html is present
  const iframeSrcDoc = useMemo(() => html ?? '', [html]);

  const hasGraphData = nodes.length > 0 || edges.length > 0;

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Visualization</h1>
          <p className="text-muted-foreground">Explore code structure and relationships</p>
        </div>
      </div>

      <div className="flex gap-4 items-center flex-wrap">
        <select
          value={selectedRepo}
          onChange={(e) => setSelectedRepo(e.target.value)}
          className="px-4 py-2 border rounded-md bg-background"
          aria-label="Select repository"
        >
          <option value="">Select Repository</option>
          {repositories.map((repo) => (
            <option key={repo} value={repo}>{repo}</option>
          ))}
        </select>

        <div className="flex gap-2 flex-wrap">
          {VIZ_TYPES.map(({ type, label, icon }) => (
            <Button
              key={type}
              variant={vizType === type ? 'default' : 'outline'}
              size="sm"
              onClick={() => setVizType(type)}
            >
              {icon}
              <span className="ml-2">{label}</span>
            </Button>
          ))}
        </div>

        {vizType === 'call_chain' && (
          <form
            className="flex gap-2 items-center"
            onSubmit={(e) => {
              e.preventDefault();
              setShowSuggestions(false);
              loadVisualization();
            }}
          >
            <div className="relative">
              <input
                type="text"
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                placeholder="Symbol name (e.g. handle_webhook)"
                className="px-3 py-1.5 border rounded-md bg-background text-sm w-72"
                aria-label="Symbol name for call chain"
                autoComplete="off"
              />
              {showSuggestions && suggestions.length > 0 && (
                <ul className="absolute z-10 w-full mt-1 bg-background border rounded-md shadow-lg max-h-60 overflow-auto">
                  {suggestions.map((s) => (
                    <li
                      key={`${s.name}-${s.file_path}`}
                      className="px-3 py-2 cursor-pointer hover:bg-muted text-sm"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setSymbolInput(s.name);
                        setShowSuggestions(false);
                      }}
                    >
                      <span className="font-medium">{s.name}</span>
                      <span className="text-muted-foreground ml-2 text-xs">
                        {s.kind} · {s.file_path?.split('/').pop()}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <Button type="submit" size="sm" disabled={!symbolInput.trim()}>
              Trace
            </Button>
          </form>
        )}

        <Button variant="outline" size="sm" onClick={loadVisualization} aria-label="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <Card className="min-h-[600px]">
        <CardContent className="p-0 relative">
          {error ? (
            <div className="flex flex-col items-center justify-center h-[600px] text-red-600 dark:text-red-400">
              <p className="font-medium">Error loading visualization</p>
              <p className="text-sm mt-2">{error}</p>
              <Button
                variant="outline"
                className="mt-4"
                onClick={() => { setError(null); loadVisualization(); }}
              >
                Retry
              </Button>
            </div>
          ) : isLoading ? (
            <div className="flex items-center justify-center h-[600px] text-muted-foreground">
              Loading visualization...
            </div>
          ) : !selectedRepo ? (
            <div className="flex flex-col items-center justify-center h-[600px] text-muted-foreground">
              <Network className="h-16 w-16 mb-4 opacity-50" />
              <p>Select a repository to visualize</p>
            </div>
          ) : html ? (
            <iframe
              srcDoc={iframeSrcDoc}
              sandbox="allow-scripts"
              title={`${vizType} visualization`}
              className="w-full h-[600px] border-0"
            />
          ) : hasGraphData ? (
            <div className="flex gap-4 h-[600px]">
              <div className="flex-1 relative">
                <GraphCanvas
                  nodes={nodes}
                  edges={edges}
                  onNodeClick={setSelectedNode}
                  selectedNodeId={selectedNode?.id}
                  className="h-full"
                />
                <div className="absolute top-4 left-4">
                  <Badge variant="secondary">
                    {nodes.length} nodes, {edges.length} edges
                  </Badge>
                </div>
              </div>
              {selectedNode && (
                <div className="w-80 shrink-0">
                  <NodeDetails
                    node={selectedNode}
                    onClose={() => setSelectedNode(null)}
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[600px] text-muted-foreground">
              <Network className="h-16 w-16 mb-4 opacity-50" />
              <p>No visualization data available</p>
              <p className="text-sm">Ingest a repository to generate graph data</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
