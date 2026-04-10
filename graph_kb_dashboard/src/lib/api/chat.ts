import { apiClient } from './client';
import type { SourceItem, WorkflowProgress } from '@/lib/types/api';

export interface AskCodeRequest {
  query: string;
  repo_id?: string;
  repo_ids?: string[];  // Multi-repo: when provided with 2+ entries, overrides repo_id
  top_k?: number;
  conversation_id?: string;
}

export interface AskCodeResponse {
  answer: string;
  sources: SourceItem[];
  mermaid_diagrams: string[];
  model?: string | null;
  workflow_id?: string;
  intent?: string | null;
}

export function askCode(request: AskCodeRequest): Promise<AskCodeResponse> {
  return apiClient.post<AskCodeResponse>('/chat/ask', request);
}

export interface AskCodeStreamCallbacks {
  onChunk: (chunk: string) => void;
  onSources: (sources: SourceItem[], metadata?: { total_sources?: number; workflow_id?: string }) => void;
  onMermaidDiagrams: (diagrams: string[]) => void;
  onProgress: (progress: WorkflowProgress) => void;
  onDone: (response: AskCodeResponse) => void;
  onError: (error: Error) => void;
}

export function askCodeStream(
  request: AskCodeRequest & { context_files?: Array<{ name: string; content: string; mimeType: string }> },
  callbacks: AskCodeStreamCallbacks,
): AbortController {
  const controller = new AbortController();
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000/api/v1';

  (async () => {
    try {
      const response = await fetch(`${API_BASE}/chat/ask/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Stream request failed: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      const finalResponse: AskCodeResponse = { answer: '', sources: [], mermaid_diagrams: [] };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6).trim();
          if (data === '[DONE]') {
            callbacks.onDone(finalResponse);
            return;
          }
          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            const type = parsed.type as string;
            if (type === 'chunk' || type === 'text') {
              const chunk = (parsed.content ?? parsed.text ?? parsed.chunk ?? '') as string;
              finalResponse.answer += chunk;
              callbacks.onChunk(chunk);
            } else if (type === 'sources') {
              const sources = (parsed.sources ?? []) as SourceItem[];
              finalResponse.sources = sources;
              callbacks.onSources(sources, {
                total_sources: parsed.total_sources as number,
                workflow_id: parsed.workflow_id as string,
              });
            } else if (type === 'mermaid') {
              const diagrams = (parsed.diagrams ?? []) as string[];
              finalResponse.mermaid_diagrams = diagrams;
              callbacks.onMermaidDiagrams(diagrams);
            } else if (type === 'progress') {
              callbacks.onProgress(parsed as unknown as WorkflowProgress);
            } else if (type === 'done' || type === 'complete') {
              if (parsed.answer) finalResponse.answer = parsed.answer as string;
              if (parsed.sources) finalResponse.sources = parsed.sources as SourceItem[];
              if (parsed.mermaid_diagrams) finalResponse.mermaid_diagrams = parsed.mermaid_diagrams as string[];
              if (parsed.model) finalResponse.model = parsed.model as string;
              if (parsed.workflow_id) finalResponse.workflow_id = parsed.workflow_id as string;
              callbacks.onDone(finalResponse);
              return;
            }
          } catch {
            // ignore parse errors
          }
        }
      }
      callbacks.onDone(finalResponse);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      callbacks.onError(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return controller;
}

export async function askCodeStreamFetch(request: AskCodeRequest): Promise<Response> {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000/api/v1';
  return fetch(`${API_BASE}/chat/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}
