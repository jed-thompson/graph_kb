const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws';

const CLIENT_ID_KEY = 'graphkb_client_id';

function getOrCreateClientId(): string {
  if (typeof window === 'undefined') return crypto.randomUUID();
  let id = localStorage.getItem(CLIENT_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(CLIENT_ID_KEY, id);
  }
  return id;
}

const WS_URL = `${WS_BASE_URL}?client_id=${getOrCreateClientId()}`;

type EventCallback = (data: unknown) => void;

class GraphKBWebSocket {
  private socket: WebSocket | null = null;
  private listeners: Map<string, Set<EventCallback>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _isConnected = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private readonly baseReconnectDelay = 1000; // 1 second
  private readonly maxReconnectDelay = 30000; // 30 seconds
  private lastPingTime: number | null = null;
  private pingCheckInterval: ReturnType<typeof setInterval> | null = null;

  get isConnected(): boolean {
    return this._isConnected;
  }

  connect(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      console.log('[WebSocket] Already connected or connecting, skipping');
      return;
    }

    console.log(`[WebSocket] Attempting to connect to ${WS_URL} (attempt ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
    
    try {
      this.socket = new WebSocket(WS_URL);
    } catch (error) {
      console.error('[WebSocket] Failed to create WebSocket:', error);
      this.scheduleReconnect();
      return;
    }

    this.socket.onopen = () => {
      console.log('[WebSocket] Connection established successfully');
      this._isConnected = true;
      this.reconnectAttempts = 0; // Reset on successful connection
      this.lastPingTime = Date.now();
      this.startPingCheck();
      this.emit('connected', {});
    };

    this.socket.onclose = (event) => {
      console.log(`[WebSocket] Connection closed: code=${event.code}, reason=${event.reason || 'none'}, clean=${event.wasClean}`);
      this._isConnected = false;
      this.stopPingCheck();
      this.emit('disconnected', { code: event.code, reason: event.reason });
      
      // Only reconnect if not a normal closure
      if (event.code !== 1000) {
        this.scheduleReconnect();
      }
    };

    this.socket.onerror = (err) => {
      console.error('[WebSocket] Error occurred:', err);
      this.emit('ws_error', err);
      this.emit('error', err);
    };

    this.socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const type: string = data.type ?? 'message';
        
        // Handle ping messages to track connection health
        if (type === 'ping') {
          this.lastPingTime = Date.now();
          // Optionally respond with pong (not required but good practice)
          this.send({ type: 'pong', timestamp: data.data?.timestamp });
        }
        
        this.emit(type, data);
        this.emit('*', data);
      } catch (error) {
        console.warn('[WebSocket] Failed to parse message:', error);
      }
    };
  }

  disconnect(): void {
    console.log('[WebSocket] Disconnecting...');
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPingCheck();
    this.socket?.close(1000, 'Client disconnect');
    this.socket = null;
    this._isConnected = false;
    this.reconnectAttempts = 0;
  }

  private startPingCheck(): void {
    // Check for missed pings every 35 seconds (server sends every 25s)
    this.pingCheckInterval = setInterval(() => {
      if (this.lastPingTime && Date.now() - this.lastPingTime > 35000) {
        console.warn('[WebSocket] No ping received for 35s, connection may be stale');
        // Don't auto-disconnect, let the server close it
      }
    }, 35000);
  }

  private stopPingCheck(): void {
    if (this.pingCheckInterval) {
      clearInterval(this.pingCheckInterval);
      this.pingCheckInterval = null;
    }
    this.lastPingTime = null;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      console.log('[WebSocket] Reconnect already scheduled');
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(`[WebSocket] Max reconnection attempts (${this.maxReconnectAttempts}) reached. Giving up.`);
      this.emit('max_reconnect_attempts', { attempts: this.reconnectAttempts });
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(
      this.baseReconnectDelay * Math.pow(2, this.reconnectAttempts),
      this.maxReconnectDelay
    );
    
    this.reconnectAttempts++;
    console.log(`[WebSocket] Scheduling reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
    
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  send(message: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    } else {
      console.warn('[WebSocket] Cannot send message, socket not open. State:', this.socket?.readyState);
    }
  }

  /**
   * Reset reconnection attempts counter.
   * Useful when user manually triggers a reconnect.
   */
  resetReconnectAttempts(): void {
    console.log('[WebSocket] Resetting reconnection attempts');
    this.reconnectAttempts = 0;
  }

  /**
   * Force a reconnection attempt.
   * Resets the attempt counter and tries to connect immediately.
   */
  forceReconnect(): void {
    console.log('[WebSocket] Force reconnecting...');
    this.disconnect();
    this.resetReconnectAttempts();
    this.connect();
  }

  on(event: string, callback: EventCallback): () => void {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(callback);
    return () => this.listeners.get(event)?.delete(callback);
  }

  private emit(event: string, data: unknown): void {
    this.listeners.get(event)?.forEach(cb => cb(data));
  }

  startIngestWorkflow(gitUrl: string, branch = 'main'): void {
    this.send({
      type: 'start',
      payload: {
        workflow_type: 'ingest',
        git_url: gitUrl,
        branch,
      },
    });
  }

  cancelWorkflow(): void {
    this.send({ type: 'cancel' });
  }

  startAskCodeWorkflow(query: string, repoId?: string): void {
    this.send({
      type: 'start',
      payload: {
        workflow_type: 'ask-code',
        query,
        repo_id: repoId,
      },
    });
  }

  startMultiRepoResearch(payload: {
    repo_ids: string[];
    relationships: Array<{
      source_repo_id: string;
      target_repo_id: string;
      relationship_type: 'dependency' | 'rest' | 'grpc';
    }>;
    strategy: 'parallel_merge' | 'dependency_aware';
    web_urls?: string[];
    document_ids?: string[];
    query?: string;
  }): void {
    this.send({
      type: 'research.start',
      payload,
    });
  }
}

let _instance: GraphKBWebSocket | null = null;

export function getWebSocket(_url?: string): GraphKBWebSocket {
  if (!_instance) {
    _instance = new GraphKBWebSocket();
  }
  return _instance;
}

export default GraphKBWebSocket;
