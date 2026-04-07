'use client';

import { useWebSocket } from '@/context/WebSocketContext';
import { useEffect, useState } from 'react';

export function WebSocketStatus() {
  const wsContext = useWebSocket();
  const [showStatus, setShowStatus] = useState(false);

  // Show status indicator when there's an error or disconnected
  useEffect(() => {
    if (wsContext?.connectionError || (!wsContext?.isConnected && (wsContext?.reconnectAttempts ?? 0) > 0)) {
      setShowStatus(true);
    } else if (wsContext?.isConnected) {
      // Hide after successful connection (with delay)
      const timer = setTimeout(() => setShowStatus(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [wsContext?.isConnected, wsContext?.connectionError, wsContext?.reconnectAttempts]);

  if (!wsContext || !showStatus) return null;

  const { isConnected, connectionError, reconnectAttempts, maxReconnectAttempts, forceReconnect } = wsContext;

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm">
      <div
        className={`rounded-lg border p-4 shadow-lg ${
          isConnected
            ? 'border-green-200 bg-green-50 text-green-800'
            : connectionError
            ? 'border-red-200 bg-red-50 text-red-800'
            : 'border-yellow-200 bg-yellow-50 text-yellow-800'
        }`}
      >
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0">
            {isConnected ? (
              <svg className="h-5 w-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                  clipRule="evenodd"
                />
              </svg>
            ) : connectionError ? (
              <svg className="h-5 w-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
            ) : (
              <svg className="h-5 w-5 animate-spin text-yellow-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-medium">
              {isConnected
                ? 'Connected'
                : connectionError
                ? 'Connection Failed'
                : 'Reconnecting...'}
            </h3>
            <div className="mt-1 text-sm">
              {isConnected ? (
                <p>WebSocket connection established</p>
              ) : connectionError ? (
                <>
                  <p>{connectionError}</p>
                  <button
                    onClick={forceReconnect}
                    className="mt-2 rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700"
                  >
                    Retry Connection
                  </button>
                </>
              ) : (
                <p>
                  Attempt {reconnectAttempts} of {maxReconnectAttempts}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={() => setShowStatus(false)}
            className="flex-shrink-0 text-gray-400 hover:text-gray-600"
          >
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
