import { apiClient } from './client';
import type { VisualizationResponse, VisualizationType } from '@/lib/types/api';

export function getVisualization(
  repoId: string,
  vizType: VisualizationType,
  options?: { symbolName?: string; direction?: string; limit?: number; maxDepth?: number },
): Promise<VisualizationResponse> {
  const params = new URLSearchParams();
  if (options?.symbolName) params.set('symbol_name', options.symbolName);
  if (options?.direction) params.set('direction', options.direction);
  if (options?.limit != null) params.set('limit', String(options.limit));
  if (options?.maxDepth != null) params.set('max_depth', String(options.maxDepth));
  const query = params.toString();
  return apiClient.get<VisualizationResponse>(
    `/visualize/repos/${repoId}/${vizType}${query ? `?${query}` : ''}`,
  );
}
