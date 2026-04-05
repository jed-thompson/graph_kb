import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1';
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';

interface ChatRequest {
  messages: Array<{
    id: string;
    role: string;
    content: string;
  }>;
  model?: string;
  stream?: boolean;
  repoId?: string;
}

interface SSEMessage {
  type: 'content' | 'sources' | 'progress' | 'tool_call' | 'clarification' | 'done' | 'error';
  content?: string;
  sources?: Array<{
    file_path: string;
    start_line: number;
    end_line: number;
    content: string;
    score: number;
  }>;
  progress?: {
    step: string;
    percent: number;
    message?: string;
  };
  tool_call?: {
    name: string;
    args: Record<string, unknown>;
  };
  clarification?: {
    question: string;
    options?: string[];
  };
  error?: string;
}

interface SearchItem {
  file_path: string;
  start_line: number;
  end_line: number;
  content: string;
  score: number;
}

interface SearchData {
  items: SearchItem[];
  total_found: number;
}

/**
 * Parse command from message content
 */
function parseCommand(content: string): { command: string | null; args: string[] } {
  const trimmed = content.trim();
  if (!trimmed.startsWith('/')) {
    return { command: null, args: [] };
  }

  const parts = trimmed.slice(1).split(/\s+/);
  const command = parts[0] || null;
  const args = parts.slice(1);
  return { command, args };
}

/**
 * Execute search command using REST API
 */
async function executeSearch(query: string, repoId?: string): Promise<{ sources: SSEMessage['sources']; answer: string }> {
  if (!repoId) {
    throw new Error('No repository selected. Please select a repository first.');
  }

  try {
    const response = await fetch(`${API_BASE_URL}/repos/${repoId}/retrieve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        top_k: 10,
        max_depth: 2,
      }),
    });

    if (!response.ok) {
      throw new Error(`Search failed: ${response.statusText}`);
    }

    const data = await response.json() as SearchData;
    const sources = data.items.map((item: SearchItem) => ({
      file_path: item.file_path,
      start_line: item.start_line,
      end_line: item.end_line,
      content: item.content,
      score: item.score,
    }));

    return {
      sources,
      answer: `Found ${data.total_found} results for "${query}". Review the sources below for relevant code snippets.`,
    };
  } catch (error) {
    throw new Error(`Search error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * List repositories using REST API
 */
async function listRepositories(): Promise<{ id: string; name?: string; status?: string }[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/repos`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`Failed to list repositories: ${response.statusText}`);
    }

    const data = await response.json() as { repos: { id: string; name?: string; status?: string }[] };
    return data.repos || [];
  } catch (error) {
    throw new Error(`List repos error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Get repository status using REST API
 */
async function getRepoStatus(repoId: string): Promise<Record<string, unknown>> {
  try {
    const response = await fetch(`${API_BASE_URL}/repos/${repoId}/stats`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`Failed to get status: ${response.statusText}`);
    }

    return await response.json() as Record<string, unknown>;
  } catch (error) {
    throw new Error(`Status error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Get architecture using REST API
 */
async function getArchitecture(repoId: string): Promise<Record<string, unknown>> {
  try {
    const response = await fetch(`${API_BASE_URL}/repos/${repoId}/architecture`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`Failed to get architecture: ${response.statusText}`);
    }

    return await response.json() as Record<string, unknown>;
  } catch (error) {
    throw new Error(`Architecture error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * WebSocket message types from backend
 */
interface WSMessage {
  type: string;
  payload?: unknown;
  data?: unknown;
  workflow_id?: string;
  event_id?: string;
  timestamp?: string;
}

/**
 * Create a WebSocket connection and return a message iterator
 */
function createWebSocketIterator(
  workflowType: string,
  payload: Record<string, unknown>
): {
  iterator: AsyncGenerator<WSMessage, void, unknown>;
  close: () => void;
} {
  const messageQueue: WSMessage[] = [];
  const resolveQueue: ((value: IteratorResult<WSMessage>) => void)[] = [];
  let isDone = false;
  let hasError: Error | null = null;

  // Helper to resolve pending promises or queue messages
  const handleMessage = (msg: WSMessage): void => {
    if (resolveQueue.length > 0) {
      const resolve = resolveQueue.shift()!;
      resolve({ value: msg, done: false });
    } else {
      messageQueue.push(msg);
    }
  };

  const handleComplete = (): void => {
    isDone = true;
    // Resolve all pending promises
    while (resolveQueue.length > 0) {
      const resolve = resolveQueue.shift()!;
      resolve({ value: undefined, done: true });
    }
  };

  // Create WebSocket connection
  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    ws.send(JSON.stringify({
      type: 'start',
      payload: {
        workflow_type: workflowType,
        ...payload,
      },
    }));
  };

  ws.onmessage = (event) => {
    try {
      const raw = JSON.parse(event.data) as WSMessage;
      // Backend sends payload in `data` field; normalize to `payload` for consumers
      const msg: WSMessage = {
        ...raw,
        payload: raw.data ?? raw.payload,
      };
      handleMessage(msg);

      // Check for completion
      if (msg.type === 'complete' || msg.type === 'error') {
        handleComplete();
      }
    } catch (e) {
      console.error('Error parsing WS message:', e);
    }
  };

  ws.onerror = () => {
    hasError = new Error('WebSocket error');
    handleComplete();
  };

  ws.onclose = () => {
    handleComplete();
  };

  // Create async generator function
  async function* generator(): AsyncGenerator<WSMessage, void, unknown> {
    while (!isDone) {
      if (hasError) {
        throw hasError;
      }

      if (messageQueue.length > 0) {
        const msg = messageQueue.shift()!;
        yield msg;
        continue;
      }

      if (isDone) {
        return;
      }

      // Wait for next message
      const result = await new Promise<IteratorResult<WSMessage>>((resolve) => {
        resolveQueue.push(resolve);
      });

      if (result.done) {
        return;
      }

      yield result.value;
    }
  }

  return {
    iterator: generator(),
    close: () => {
      handleComplete();
      ws.close();
    },
  };
}

/**
 * Generate stream from async operations
 */
async function* generateChatStream(
  request: ChatRequest
): AsyncGenerator<SSEMessage, void, unknown> {
  const lastMessage = request.messages[request.messages.length - 1];
  if (!lastMessage) {
    yield { type: 'error', error: 'No message provided' };
    return;
  }

  const { command, args } = parseCommand(lastMessage.content);

  // Handle commands
  if (command) {
    switch (command) {
      // ============================================
      // Search Commands
      // ============================================
      case 'search': {
        const query = args.join(' ') || lastMessage.content.slice(7).trim();
        yield { type: 'progress', progress: { step: 'searching', percent: 25, message: 'Searching codebase...' } };

        try {
          const result = await executeSearch(query, request.repoId);
          yield { type: 'sources', sources: result.sources };
          yield { type: 'content', content: result.answer };
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Search failed' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Ask Commands - Uses WebSocket workflow
      // ============================================
      case 'ask':
      case 'deep': {
        const query = args.join(' ') || lastMessage.content.replace(/^\/(ask|deep)\s*/, '').trim();
        if (!request.repoId) {
          yield { type: 'error', error: 'No repository selected. Use /search instead to query code.' };
          yield { type: 'done' };
          return;
        }

        const workflowType = command === 'deep' ? 'multi_agent' : 'ask-code';
        yield { type: 'progress', progress: { step: 'connecting', percent: 10, message: 'Connecting to workflow...' } };

        try {
          const { iterator, close } = createWebSocketIterator(workflowType, {
            query,
            repo_id: request.repoId,
          });

          try {
            for await (const msg of iterator) {
              switch (msg.type) {
                case 'progress':
                  yield {
                    type: 'progress',
                    progress: {
                      step: (msg.payload as { step?: string })?.step || 'processing',
                      percent: (msg.payload as { progress_percent?: number; percent?: number })?.progress_percent ?? (msg.payload as { percent?: number })?.percent ?? 50,
                      message: (msg.payload as { message?: string })?.message,
                    },
                  };
                  break;

                case 'partial':
                  yield {
                    type: 'content',
                    content: (msg.payload as { content?: string })?.content || '',
                  };
                  break;

                case 'tool_call':
                  yield {
                    type: 'tool_call',
                    tool_call: {
                      name: (msg.payload as { name?: string })?.name || 'unknown',
                      args: (msg.payload as { args?: Record<string, unknown> })?.args || {},
                    },
                  };
                  break;

                case 'clarification':
                  yield {
                    type: 'clarification',
                    clarification: {
                      question: (msg.payload as { question?: string })?.question || '',
                      options: (msg.payload as { options?: string[] })?.options,
                    },
                  };
                  break;

                case 'complete':
                  if ((msg.payload as { result?: string })?.result) {
                    yield { type: 'content', content: (msg.payload as { result: string }).result };
                  } else if ((msg.payload as { response?: string })?.response) {
                    yield { type: 'content', content: (msg.payload as { response: string }).response };
                  }
                  break;

                case 'error':
                  yield {
                    type: 'error',
                    error: (msg.payload as { message?: string })?.message || 'Workflow error',
                  };
                  break;
              }
            }
          } finally {
            close();
          }
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Workflow failed' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Ingest Command - Uses WebSocket workflow
      // ============================================
      case 'ingest': {
        const gitUrl = args[0];
        const branch = args[1] || 'main';

        if (!gitUrl) {
          yield { type: 'error', error: 'Usage: /ingest <git-url> [branch]' };
          yield { type: 'done' };
          return;
        }

        yield { type: 'progress', progress: { step: 'connecting', percent: 10, message: 'Starting ingest workflow...' } };

        try {
          const { iterator, close } = createWebSocketIterator('ingest', {
            git_url: gitUrl,
            branch,
          });

          try {
            for await (const msg of iterator) {
              switch (msg.type) {
                case 'progress':
                  yield {
                    type: 'progress',
                    progress: {
                      step: (msg.payload as { step?: string })?.step || 'ingesting',
                      percent: (msg.payload as { progress_percent?: number; percent?: number })?.progress_percent ?? (msg.payload as { percent?: number })?.percent ?? 50,
                      message: (msg.payload as { message?: string })?.message,
                    },
                  };
                  break;

                case 'partial':
                  yield {
                    type: 'content',
                    content: (msg.payload as { content?: string })?.content || '',
                  };
                  break;

                case 'clarification':
                  yield {
                    type: 'clarification',
                    clarification: {
                      question: (msg.payload as { question?: string })?.question || '',
                      options: (msg.payload as { options?: string[] })?.options,
                    },
                  };
                  break;

                case 'complete':
                  yield {
                    type: 'content',
                    content: `✅ Ingest complete!\n${JSON.stringify(msg.payload, null, 2)}`,
                  };
                  break;

                case 'error':
                  yield {
                    type: 'error',
                    error: (msg.payload as { message?: string })?.message || 'Ingest failed',
                  };
                  break;
              }
            }
          } finally {
            close();
          }
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Failed to start ingest' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Diff Command - Uses WebSocket workflow
      // ============================================
      case 'diff': {
        const repoId = args[0] || request.repoId;
        const fromCommit = args[1];
        const toCommit = args[2];

        if (!repoId) {
          yield { type: 'error', error: 'Usage: /diff [repo-id] <from-commit> [to-commit]' };
          yield { type: 'done' };
          return;
        }

        if (!fromCommit) {
          yield { type: 'error', error: 'Usage: /diff [repo-id] <from-commit> [to-commit] - from-commit is required' };
          yield { type: 'done' };
          return;
        }

        yield { type: 'progress', progress: { step: 'connecting', percent: 10, message: 'Starting diff workflow...' } };

        try {
          const { iterator, close } = createWebSocketIterator('diff', {
            repo_id: repoId,
            from_commit: fromCommit,
            to_commit: toCommit,
          });

          try {
            for await (const msg of iterator) {
              switch (msg.type) {
                case 'progress':
                  yield {
                    type: 'progress',
                    progress: {
                      step: (msg.payload as { step?: string })?.step || 'diffing',
                      percent: (msg.payload as { progress_percent?: number; percent?: number })?.progress_percent ?? (msg.payload as { percent?: number })?.percent ?? 50,
                      message: (msg.payload as { message?: string })?.message,
                    },
                  };
                  break;

                case 'partial':
                  yield {
                    type: 'content',
                    content: (msg.payload as { content?: string })?.content || '',
                  };
                  break;

                case 'complete':
                  yield {
                    type: 'content',
                    content: `✅ Diff complete!\n${JSON.stringify(msg.payload, null, 2)}`,
                  };
                  break;

                case 'error':
                  yield {
                    type: 'error',
                    error: (msg.payload as { message?: string })?.message || 'Diff failed',
                  };
                  break;
              }
            }
          } finally {
            close();
          }
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Failed to start diff' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // List Repositories
      // ============================================
      case 'list':
      case 'repos': {
        yield { type: 'progress', progress: { step: 'listing', percent: 25, message: 'Fetching repositories...' } };

        try {
          const repos = await listRepositories();
          if (repos.length === 0) {
            yield { type: 'content', content: 'No repositories found. Use `/ingest <git-url>` to add one.' };
          } else {
            const repoList = repos.map(r => `- **${r.id}** ${r.status ? `(${r.status})` : ''}`).join('\n');
            yield { type: 'content', content: `📚 **Repositories (${repos.length}):**\n\n${repoList}` };
          }
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Failed to list repositories' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Status Command
      // ============================================
      case 'status': {
        const repoId = args[0] || request.repoId;
        if (!repoId) {
          yield { type: 'error', error: 'Usage: /status [repo-id] - No repository selected' };
          yield { type: 'done' };
          return;
        }

        yield { type: 'progress', progress: { step: 'checking', percent: 25, message: 'Fetching status...' } };

        try {
          const stats = await getRepoStatus(repoId);
          yield {
            type: 'content',
            content: `📊 **Repository Status: ${repoId}**\n\n\`\`\`json\n${JSON.stringify(stats, null, 2)}\n\`\`\``,
          };
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Failed to get status' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Architecture Command
      // ============================================
      case 'architecture':
      case 'arch': {
        const repoId = args[0] || request.repoId;
        if (!repoId) {
          yield { type: 'error', error: 'Usage: /architecture [repo-id] - No repository selected' };
          yield { type: 'done' };
          return;
        }

        yield { type: 'progress', progress: { step: 'analyzing', percent: 25, message: 'Fetching architecture...' } };

        try {
          const arch = await getArchitecture(repoId);
          yield {
            type: 'content',
            content: `🏗️ **Architecture: ${repoId}**\n\n\`\`\`json\n${JSON.stringify(arch, null, 2)}\n\`\`\``,
          };
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Failed to get architecture' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Help Command
      // ============================================
      case 'help':
      case '?': {
        const helpText = `## 📖 GraphKB Commands

### Search & Query
- \`/search <query>\` - Search code in the repository
- \`/ask <question>\` - Ask a question about the code (uses AI)
- \`/deep <question>\` - Deep analysis with multi-agent workflow

### Repository Management
- \`/ingest <git-url> [branch]\` - Ingest a git repository
- \`/diff <from-commit> [to-commit]\` - Analyze changes between commits
- \`/list\` - List all repositories
- \`/status [repo-id]\` - Get repository status

### Analysis
- \`/architecture [repo-id]\` - View repository architecture
- \`/visualize\` - Open visualization page
- \`/stats\` - Open graph statistics page

### Help
- \`/help\` or \`/?\` - Show this help message

### Tips
- Most commands work with the currently selected repository
- Use the dropdown in the sidebar to switch repositories
- For detailed visualization, visit the /visualize page`;
        yield { type: 'content', content: helpText };
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Navigation Commands
      // ============================================
      case 'visualize':
      case 'viz': {
        yield {
          type: 'content',
          content: `📈 **Visualization**\n\nVisit the [Visualization page](/visualize) to explore the code graph interactively.`,
        };
        yield { type: 'done' };
        return;
      }

      case 'stats':
      case 'graph-stats': {
        yield {
          type: 'content',
          content: `📊 **Graph Statistics**\n\nVisit the [Graph Stats page](/graph-stats) to view detailed statistics about the knowledge graph.`,
        };
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Multi-Agent Command
      // ============================================
      case 'multi-agent':
      case 'agent': {
        const query = args.join(' ');
        if (!query) {
          yield { type: 'error', error: 'Usage: /multi-agent <task> - Please provide a task for the multi-agent workflow' };
          yield { type: 'done' };
          return;
        }
        if (!request.repoId) {
          yield { type: 'error', error: 'No repository selected. Please select a repository first.' };
          yield { type: 'done' };
          return;
        }

        yield { type: 'progress', progress: { step: 'connecting', percent: 10, message: 'Starting multi-agent workflow...' } };

        try {
          const { iterator, close } = createWebSocketIterator('multi_agent', {
            query,
            repo_id: request.repoId,
          });

          try {
            for await (const msg of iterator) {
              switch (msg.type) {
                case 'progress':
                  yield {
                    type: 'progress',
                    progress: {
                      step: (msg.payload as { step?: string })?.step || 'processing',
                      percent: (msg.payload as { progress_percent?: number; percent?: number })?.progress_percent ?? (msg.payload as { percent?: number })?.percent ?? 50,
                      message: (msg.payload as { message?: string })?.message,
                    },
                  };
                  break;

                case 'partial':
                  yield {
                    type: 'content',
                    content: (msg.payload as { content?: string })?.content || '',
                  };
                  break;

                case 'tool_call':
                  yield {
                    type: 'tool_call',
                    tool_call: {
                      name: (msg.payload as { name?: string })?.name || 'unknown',
                      args: (msg.payload as { args?: Record<string, unknown> })?.args || {},
                    },
                  };
                  break;

                case 'clarification':
                  yield {
                    type: 'clarification',
                    clarification: {
                      question: (msg.payload as { question?: string })?.question || '',
                      options: (msg.payload as { options?: string[] })?.options,
                    },
                  };
                  break;

                case 'complete':
                  if ((msg.payload as { result?: string })?.result) {
                    yield { type: 'content', content: (msg.payload as { result: string }).result };
                  } else if ((msg.payload as { response?: string })?.response) {
                    yield { type: 'content', content: (msg.payload as { response: string }).response };
                  }
                  break;

                case 'error':
                  yield {
                    type: 'error',
                    error: (msg.payload as { message?: string })?.message || 'Multi-agent workflow error',
                  };
                  break;
              }
            }
          } finally {
            close();
          }
        } catch (error) {
          yield { type: 'error', error: error instanceof Error ? error.message : 'Multi-agent workflow failed' };
        }
        yield { type: 'done' };
        return;
      }

      // ============================================
      // Unknown Command
      // ============================================
      default: {
        yield { type: 'error', error: `Unknown command: /${command}. Type /help for available commands.` };
        yield { type: 'done' };
        return;
      }
    }
  }

  // ============================================
  // Handle regular chat messages (no command)
  // ============================================
  if (!request.repoId) {
    yield { type: 'content', content: 'Please select a repository first, or use a command like /search <query> to search code. Type /help for all commands.' };
    yield { type: 'done' };
    return;
  }

  // For regular messages, use ask-code workflow
  yield { type: 'progress', progress: { step: 'connecting', percent: 10, message: 'Processing your question...' } };

  try {
    const { iterator, close } = createWebSocketIterator('ask-code', {
      query: lastMessage.content,
      repo_id: request.repoId,
    });

    try {
      for await (const msg of iterator) {
        switch (msg.type) {
          case 'progress':
            yield {
              type: 'progress',
              progress: {
                step: (msg.payload as { step?: string })?.step || 'processing',
                percent: (msg.payload as { progress_percent?: number; percent?: number })?.progress_percent ?? (msg.payload as { percent?: number })?.percent ?? 50,
                message: (msg.payload as { message?: string })?.message,
              },
            };
            break;

          case 'partial':
            yield {
              type: 'content',
              content: (msg.payload as { content?: string })?.content || '',
            };
            break;

          case 'complete':
            if ((msg.payload as { result?: string })?.result) {
              yield { type: 'content', content: (msg.payload as { result: string }).result };
            } else if ((msg.payload as { response?: string })?.response) {
              yield { type: 'content', content: (msg.payload as { response: string }).response };
            }
            break;

          case 'error':
            yield {
              type: 'error',
              error: (msg.payload as { message?: string })?.message || 'Workflow error',
            };
            break;
        }
      }
    } finally {
      close();
    }
  } catch (error) {
    // Fallback to search if WebSocket fails
    yield { type: 'progress', progress: { step: 'searching', percent: 25, message: 'Falling back to search...' } };
    try {
      const result = await executeSearch(lastMessage.content, request.repoId);
      yield { type: 'sources', sources: result.sources };
      yield { type: 'content', content: result.answer };
    } catch (searchError) {
      yield { type: 'error', error: searchError instanceof Error ? searchError.message : 'Failed to search' };
    }
  }
  yield { type: 'done' };
}

/**
 * SSE encoder
 */
function sseEncode(data: SSEMessage): string {
  return `data: ${JSON.stringify(data)}\n\n`;
}

export async function POST(req: NextRequest) {
  try {
    const body: ChatRequest = await req.json();
    const encoder = new TextEncoder();

    // Create a readable stream for SSE
    const stream = new ReadableStream({
      async start(controller) {
        try {
          const generator = generateChatStream(body);

          for await (const message of generator) {
            const encoded = sseEncode(message);
            controller.enqueue(encoder.encode(encoded));
          }
        } catch (error) {
          const errorMessage = sseEncode({
            type: 'error',
            error: error instanceof Error ? error.message : 'Stream error',
          });
          controller.enqueue(encoder.encode(errorMessage));
        } finally {
          controller.close();
        }
      },
    });

    return new NextResponse(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Invalid request' },
      { status: 400 }
    );
  }
}
