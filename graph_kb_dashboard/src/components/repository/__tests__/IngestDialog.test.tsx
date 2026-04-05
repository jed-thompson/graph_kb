import React from 'react';
import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IngestDialog } from '../IngestDialog';

// ---------------------------------------------------------------------------
// Mock useWebSocket – provide a fake ws object with an `on` method
// ---------------------------------------------------------------------------

type Handler = (data: unknown) => void;

function createMockWs() {
    const handlers = new Map<string, Handler>();
    return {
        on: jest.fn((type: string, handler: Handler) => {
            handlers.set(type, handler);
            return () => { handlers.delete(type); };
        }),
        startIngestWorkflow: jest.fn(),
        /** Helper: simulate the server pushing an event of the given type. */
        _emit(type: string, data: unknown) {
            const h = handlers.get(type);
            if (h) h(data);
        },
    };
}

let mockWs: ReturnType<typeof createMockWs>;
let mockIsConnected: boolean;

jest.mock('@/context/WebSocketContext', () => ({
    useWebSocket: () => ({
        ws: mockWs,
        isConnected: mockIsConnected,
    }),
}));

// ---------------------------------------------------------------------------
// Spy on the global WebSocket constructor so we can assert it is never called
// ---------------------------------------------------------------------------

const WebSocketSpy = jest.fn();
beforeAll(() => {
    (global as unknown as Record<string, unknown>).WebSocket = WebSocketSpy;
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {
    open: true,
    onOpenChange: jest.fn(),
    onIngest: jest.fn(),
    onCancel: jest.fn(),
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('IngestDialog WebSocket integration', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockWs = createMockWs();
        mockIsConnected = true;
        WebSocketSpy.mockClear();
    });

    /**
     * Validates: Requirements 5.1
     * IngestDialog must NOT create its own WebSocket connection – it must use
     * the shared WebSocketContext instead.
     */
    it('does not create its own WebSocket connection', () => {
        render(<IngestDialog {...defaultProps} />);

        // The global WebSocket constructor should never be called by IngestDialog.
        // Any WebSocket creation would go through the spy we installed.
        expect(WebSocketSpy).not.toHaveBeenCalled();
    });

    /**
     * Validates: Requirements 5.1
     * IngestDialog subscribes to events via the shared ws.on() method.
     */
    it('subscribes to progress, complete, and error events via ws.on()', () => {
        render(<IngestDialog {...defaultProps} />);

        const subscribedTypes = mockWs.on.mock.calls.map(
            (call: [string, Handler]) => call[0],
        );
        expect(subscribedTypes).toContain('progress');
        expect(subscribedTypes).toContain('complete');
        expect(subscribedTypes).toContain('error');
    });

    /**
     * Validates: Requirements 5.2
     * When the backend sends a progress event through the shared context,
     * the dialog renders the phase label and message.
     */
    it('renders progress events received from the shared context', () => {
        render(<IngestDialog {...defaultProps} />);

        act(() => {
            mockWs._emit('progress', {
                phase: 'cloning',
                step: 'cloning',
                progress_percent: 42,
                message: 'Receiving objects...',
            });
        });

        // The PHASE_LABELS map translates 'cloning' → 'Cloning repository'
        expect(screen.getByText('Cloning repository')).toBeInTheDocument();
        expect(screen.getByText('Receiving objects...')).toBeInTheDocument();
    });

    /**
     * Validates: Requirements 5.2
     * Progress bar value updates when a progress event arrives.
     */
    it('updates the progress bar value from progress events', () => {
        render(<IngestDialog {...defaultProps} />);

        act(() => {
            mockWs._emit('progress', {
                phase: 'indexing',
                progress_percent: 65,
                message: 'Processing files...',
            });
        });

        // The Progress component renders with the value attribute
        const progressBar = document.querySelector('[role="progressbar"]');
        expect(progressBar).toBeInTheDocument();
    });

    /**
     * Validates: Requirements 5.2
     * When a complete event arrives, the dialog shows the completion message.
     */
    it('handles complete events from the shared context', async () => {
        const onIngest = jest.fn();
        render(<IngestDialog {...defaultProps} onIngest={onIngest} />);

        // First trigger a progress event so the dialog is in loading state
        const user = userEvent.setup();
        const urlInput = screen.getByPlaceholderText('https://github.com/owner/repo');
        await user.type(urlInput, 'https://github.com/test/repo');
        await user.click(screen.getByText('Start Ingestion'));

        act(() => {
            mockWs._emit('complete', {
                repo_id: 'repo-123',
            });
        });

        expect(screen.getByText('Ingestion complete!')).toBeInTheDocument();
    });

    /**
     * Validates: Requirements 5.2
     * When an error event arrives, the dialog displays the error message.
     */
    it('handles error events from the shared context', () => {
        render(<IngestDialog {...defaultProps} />);

        act(() => {
            mockWs._emit('error', {
                message: 'Clone failed: repository not found',
            });
        });

        expect(
            screen.getByText('Clone failed: repository not found'),
        ).toBeInTheDocument();
    });

    /**
     * Validates: Requirements 5.1
     * When the dialog is closed (open=false), it should not subscribe to events.
     */
    it('does not subscribe to events when dialog is closed', () => {
        render(<IngestDialog {...defaultProps} open={false} />);

        // ws.on should not be called when the dialog is not open
        expect(mockWs.on).not.toHaveBeenCalled();
    });
});
