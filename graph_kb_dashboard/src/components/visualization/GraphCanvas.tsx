'use client';

import React, { useCallback, useRef } from 'react';
import { ForceGraph2D } from 'react-force-graph';
import { cn } from '@/lib/utils';
import { GraphNode, GraphEdge } from '@/lib/types/api';

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick?: (node: GraphNode) => void;
  selectedNodeId?: string;
  className?: string;
}

const NODE_COLORS: Record<string, string> = {
  function: '#3b82f6',
  class: '#22c55e',
  method: '#a855f7',
  variable: '#f97316',
  default: '#64748b',
};

export const GraphCanvas: React.FC<GraphCanvasProps> = ({
  nodes,
  edges,
  onNodeClick,
  selectedNodeId,
  className,
}) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);

  const getNodeColor = useCallback((node: GraphNode) => {
    return NODE_COLORS[node.type] || NODE_COLORS.default;
  }, []);

  const handleNodeClick = useCallback((node: GraphNode) => {
    if (onNodeClick) {
      onNodeClick(node);
    }
  }, [onNodeClick]);

  const handleNodeDragEnd = useCallback(() => {
    // Optional: Save node positions if needed
  }, []);

  return (
    <div className={cn('w-full h-full', className)}>
      <ForceGraph2D
        ref={graphRef}
        graphData={{
          nodes: nodes.map(n => ({ ...n })),
          links: edges.map(e => ({
            ...e,
            source: e.source,
            target: e.target,
          })),
        }}
        nodeColor={(node: GraphNode) => getNodeColor(node)}
        nodeLabel={(node: GraphNode) => `${node.label} (${node.type})`}
        nodeCanvasObject={(node: GraphNode, ctx, globalScale) => {
          const label = node.label;
          const fontSize = 12 / globalScale;
          const nodeRadius = 8;

          // Draw node circle
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, nodeRadius, 0, 2 * Math.PI, false);
          ctx.fillStyle = getNodeColor(node);
          ctx.fill();

          // Draw border for selected node
          if (node.id === selectedNodeId) {
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 2;
            ctx.stroke();
          }

          // Draw label
          ctx.font = `${fontSize}px Sans-Serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#1e293b';
          ctx.fillText(label, node.x!, node.y! + nodeRadius + fontSize);
        }}
        linkDirectionalArrowLength={3.5}
        linkDirectionalArrowRelPos={1}
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={0.002}
        onNodeClick={handleNodeClick}
        onNodeDragEnd={handleNodeDragEnd}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        width={undefined}
        height={undefined}
        d3AlphaDecay={0.028}
        d3VelocityDecay={0.3}
        cooldownTicks={100}
      />
    </div>
  );
};

export default GraphCanvas;