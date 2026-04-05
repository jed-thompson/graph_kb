'use client';

import React from 'react';
import { X, Copy, FileText, Code2, MapPin } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { GraphNode } from '@/lib/types/api';

export interface NodeDetailsProps {
  node: GraphNode | null;
  onClose?: () => void;
}

const NODE_TYPE_COLORS: Record<string, string> = {
  function: 'bg-blue-500',
  class: 'bg-green-500',
  method: 'bg-purple-500',
  variable: 'bg-orange-500',
  default: 'bg-gray-500',
};

export const NodeDetails: React.FC<NodeDetailsProps> = ({ node, onClose }) => {
  const handleCopyFilePath = async () => {
    if (node?.file_path) {
      try {
        await navigator.clipboard.writeText(node.file_path);
      } catch (error) {
        console.error('Failed to copy file path:', error);
      }
    }
  };

  if (!node) {
    return null;
  }

  const typeColor = NODE_TYPE_COLORS[node.type] || NODE_TYPE_COLORS.default;

  return (
    <Card className="shadow-lg">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <div className={cn('w-3 h-3 rounded-full', typeColor)} />
            <CardTitle className="text-lg truncate">{node.label}</CardTitle>
          </div>
          {onClose && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0"
              onClick={onClose}
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Symbol Type */}
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{node.type}</Badge>
        </div>

        {/* File Path */}
        {node.file_path && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <FileText className="h-4 w-4" />
              <span className="font-medium">File Path</span>
            </div>
            <div className="flex items-center gap-2">
              <code className="text-xs bg-muted px-2 py-1 rounded flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
                {node.file_path}
              </code>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={handleCopyFilePath}
                title="Copy file path"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}

        {/* Line Numbers */}
        {node.start_line !== undefined && node.end_line !== undefined && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <MapPin className="h-4 w-4" />
              <span className="font-medium">Location</span>
            </div>
            <div className="text-sm">
              Lines {node.start_line} - {node.end_line}
            </div>
          </div>
        )}

        {/* Signature */}
        {node.signature && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Code2 className="h-4 w-4" />
              <span className="font-medium">Signature</span>
            </div>
            <pre className="text-xs bg-muted p-3 rounded overflow-x-auto whitespace-pre-wrap break-all">
              {node.signature}
            </pre>
          </div>
        )}

        {/* Docstring */}
        {node.docstring && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <FileText className="h-4 w-4" />
              <span className="font-medium">Documentation</span>
            </div>
            <div className="text-sm bg-muted p-3 rounded prose prose-sm dark:prose-invert max-h-40 overflow-y-auto">
              {node.docstring}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default NodeDetails;