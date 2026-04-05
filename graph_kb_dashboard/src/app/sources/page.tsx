'use client';

import { useState, useMemo, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  Folder,
  FolderOpen,
  GitBranch,
  Box,
  Code2,
  ArrowLeft,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import type { Source } from '@/lib/types/chat';
import { getSources } from '@/lib/api/sources';

interface SourceNode {
  name: string;
  type: 'repo' | 'directory' | 'file' | 'symbol';
  path: string;
  children?: Map<string, SourceNode>;
  sources?: Source[];
  lineRange?: string;
  score?: number;
}

function buildSourceTree(sources: Source[]): SourceNode {
  const root: SourceNode = {
    name: 'Sources',
    type: 'repo',
    path: '',
    children: new Map(),
  };

  for (const source of sources) {
    const parts = source.file_path.split('/').filter(Boolean);
    let current = root;

    // Build directory structure
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!current.children) {
        current.children = new Map();
      }
      if (!current.children.has(part)) {
        current.children.set(part, {
          name: part,
          type: 'directory',
          path: parts.slice(0, i + 1).join('/'),
          children: new Map(),
        });
      }
      current = current.children.get(part)!;
    }

    // Add file node
    const fileName = parts[parts.length - 1] || source.file_path;
    if (!current.children) {
      current.children = new Map();
    }

    if (!current.children.has(fileName)) {
      current.children.set(fileName, {
        name: fileName,
        type: 'file',
        path: source.file_path,
        children: new Map(),
        sources: [],
      });
    }

    const fileNode = current.children.get(fileName)!;
    if (!fileNode.sources) {
      fileNode.sources = [];
    }

    // Add symbol if available
    if (source.symbol) {
      if (!fileNode.children) {
        fileNode.children = new Map();
      }
      const symbolKey = `${source.symbol}_${source.start_line || 0}`;
      if (!fileNode.children.has(symbolKey)) {
        fileNode.children.set(symbolKey, {
          name: source.symbol,
          type: 'symbol',
          path: `${source.file_path}:${source.symbol}`,
          sources: [source],
          lineRange:
            source.start_line && source.end_line
              ? source.start_line === source.end_line
                ? `L${source.start_line}`
                : `L${source.start_line}-${source.end_line}`
              : source.start_line
                ? `L${source.start_line}`
                : undefined,
          score: source.score ?? undefined,
        });
      } else {
        fileNode.children.get(symbolKey)!.sources!.push(source);
      }
    } else {
      fileNode.sources.push(source);
    }
  }

  return root;
}

interface TreeNodeProps {
  node: SourceNode;
  depth?: number;
  defaultExpanded?: boolean;
}

function TreeNode({ node, depth = 0, defaultExpanded = false }: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded || depth < 2);
  const hasChildren = node.children && node.children.size > 0;
  const hasSources = node.sources && node.sources.length > 0;

  const getIcon = () => {
    switch (node.type) {
      case 'repo':
        return <GitBranch className="h-4 w-4 text-purple-500 dark:text-purple-400" />;
      case 'directory':
        return isExpanded ? (
          <FolderOpen className="h-4 w-4 text-yellow-500 dark:text-yellow-400" />
        ) : (
          <Folder className="h-4 w-4 text-yellow-500 dark:text-yellow-400" />
        );
      case 'file':
        return <FileCode className="h-4 w-4 text-blue-500 dark:text-blue-400" />;
      case 'symbol':
        return node.name.match(/^[A-Z]/) ? (
          <Box className="h-4 w-4 text-green-500 dark:text-green-400" />
        ) : (
          <Code2 className="h-4 w-4 text-cyan-500 dark:text-cyan-400" />
        );
      default:
        return <FileCode className="h-4 w-4 text-muted-foreground" />;
    }
  };

  const childrenArray = hasChildren ? Array.from(node.children!.values()) : [];

  return (
    <div className="select-none">
      <div
        className={`flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-muted/50 cursor-pointer transition-colors ${
          depth === 0 ? 'bg-muted/30' : ''
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => hasChildren && setIsExpanded(!isExpanded)}
      >
        {hasChildren ? (
          isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )
        ) : (
          <span className="w-4" />
        )}
        {getIcon()}
        <span className="text-sm font-medium text-foreground truncate flex-1">
          {node.name}
        </span>
        {node.lineRange && (
          <span className="text-xs text-muted-foreground font-mono">{node.lineRange}</span>
        )}
        {node.score !== undefined && (
          <span className="text-xs text-muted-foreground">
            {(node.score * 100).toFixed(0)}%
          </span>
        )}
        {hasSources && node.type === 'file' && (
          <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
            {node.sources?.length ?? 0}
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <div className="border-l border-border ml-4">
          {childrenArray.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              defaultExpanded={defaultExpanded}
            />
          ))}
        </div>
      )}

      {isExpanded && hasSources && node.type === 'file' && !hasChildren && (
        <div className="ml-8 pl-4 border-l border-border space-y-1">
          {node.sources?.map((source, idx) => (
            <div
              key={idx}
              className="text-xs text-muted-foreground py-1 px-2 bg-muted/30 rounded"
            >
              {source.start_line && (
                <span className="font-mono text-muted-foreground mr-2">
                  L{source.start_line}
                  {source.end_line && source.end_line !== source.start_line
                    ? `-${source.end_line}`
                    : ''}
                </span>
              )}
              {source.symbol && (
                <span className="text-cyan-600 dark:text-cyan-400">{source.symbol}</span>
              )}
              {source.score != null && (
                <span className="text-muted-foreground ml-2">
                  ({(source.score * 100).toFixed(0)}%)
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface SourceDetailCardProps {
  source: Source;
  index: number;
}

function SourceDetailCard({ source, index }: SourceDetailCardProps) {
  const [showContent, setShowContent] = useState(false);

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div
        className="flex items-center gap-3 p-3 cursor-pointer hover:bg-muted/50"
        onClick={() => setShowContent(!showContent)}
      >
        <FileCode className="h-4 w-4 text-blue-500 dark:text-blue-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-foreground truncate">
            {source.file_path}
          </div>
          {source.symbol && (
            <div className="text-xs text-cyan-600 dark:text-cyan-400">{source.symbol}</div>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {source.start_line && (
            <span className="font-mono bg-muted px-1.5 py-0.5 rounded">
              L{source.start_line}
              {source.end_line && source.end_line !== source.start_line
                ? `-${source.end_line}`
                : ''}
            </span>
          )}
          {source.score != null && (
            <span className="text-green-600 dark:text-green-400">
              {(source.score * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>
      {showContent && source.content && (
        <div className="border-t border-border">
          <pre className="p-3 text-xs text-muted-foreground overflow-x-auto bg-muted/50 max-h-48 overflow-y-auto">
            <code>{source.content}</code>
          </pre>
        </div>
      )}
    </div>
  );
}

export default function SourcesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const workflowId = searchParams.get('workflow_id');
  const sourcesParam = searchParams.get('data');
  const [viewMode, setViewMode] = useState<'tree' | 'cards'>('tree');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetchedSources, setFetchedSources] = useState<Source[]>([]);
  const [repoId, setRepoId] = useState<string>('');
  const [query, setQuery] = useState<string>('');

  // Fetch sources from API if workflow_id is provided
  useEffect(() => {
    if (workflowId) {
      setIsLoading(true);
      setError(null);
      getSources(workflowId)
        .then((response) => {
          setFetchedSources(response.sources as unknown as Source[]);
          setRepoId(response.repo_id);
          setQuery(response.query);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : 'Failed to fetch sources');
        })
        .finally(() => {
          setIsLoading(false);
        });
    }
  }, [workflowId]);

  // Use fetched sources or fall back to URL parameter
  const sources: Source[] = useMemo(() => {
    if (workflowId && fetchedSources.length > 0) {
      return fetchedSources;
    }
    if (!sourcesParam) return [];
    try {
      const decoded = decodeURIComponent(sourcesParam);
      return JSON.parse(decoded);
    } catch {
      return [];
    }
  }, [workflowId, fetchedSources, sourcesParam]);

  const sourceTree = useMemo(() => buildSourceTree(sources), [sources]);

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-background text-foreground p-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4 mb-6">
            <button
              onClick={() => router.back()}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-2xl font-bold">Sources</h1>
          </div>
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="ml-3 text-muted-foreground">Loading sources...</span>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="min-h-screen bg-background text-foreground p-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4 mb-6">
            <button
              onClick={() => router.back()}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-2xl font-bold">Sources</h1>
          </div>
          <div className="bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-red-500 dark:text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-red-600 dark:text-red-400">Failed to load sources</h3>
              <p className="text-sm text-muted-foreground mt-1">{error}</p>
              <p className="text-xs text-muted-foreground mt-2">
                Sources are cached for 1 hour. The cache may have expired.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (sources.length === 0 && !isLoading) {
    return (
      <div className="min-h-screen bg-background text-foreground p-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4 mb-6">
            <button
              onClick={() => router.back()}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-2xl font-bold">Sources</h1>
          </div>
          <div className="bg-card rounded-lg border border-border p-8 text-center">
            <FileCode className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">No sources available</p>
            <p className="text-sm text-muted-foreground mt-2">
              Sources will appear here after analyzing code in the chat.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.back()}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <h1 className="text-2xl font-bold">Sources</h1>
              <p className="text-sm text-muted-foreground">
                {sources.length} source{sources.length !== 1 ? 's' : ''} found
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setViewMode('tree')}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                viewMode === 'tree'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              Tree View
            </button>
            <button
              onClick={() => setViewMode('cards')}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                viewMode === 'cards'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              Card View
            </button>
          </div>
        </div>

        {/* Content */}
        {viewMode === 'tree' ? (
          <div className="bg-card rounded-lg border border-border p-4">
            <TreeNode node={sourceTree} defaultExpanded={sources.length < 50} />
          </div>
        ) : (
          <div className="grid gap-3">
            {sources.map((source, idx) => (
              <SourceDetailCard key={idx} source={source} index={idx} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
