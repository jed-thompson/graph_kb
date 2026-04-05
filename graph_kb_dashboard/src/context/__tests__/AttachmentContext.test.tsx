import React from 'react';
import '@testing-library/jest-dom';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { AttachmentProvider, useAttachments } from '../AttachmentContext';

// Helper component that exposes the context for testing
function TestConsumer() {
    const { files, addFile, removeFile, clearAll, getContextFiles } = useAttachments();

    return (
        <div>
            <span data-testid="file-count">{files.length}</span>
            <span data-testid="context-count">{getContextFiles().length}</span>
            <ul data-testid="file-list">
                {files.map((f) => (
                    <li key={f.id} data-testid={`file-${f.id}`}>
                        <span data-testid={`name-${f.id}`}>{f.name}</span>
                        <span data-testid={`mime-${f.id}`}>{f.mimeType}</span>
                        <button data-testid={`remove-${f.id}`} onClick={() => removeFile(f.id)}>
                            Remove
                        </button>
                    </li>
                ))}
            </ul>
            <button
                data-testid="add-file"
                onClick={() => {
                    const file = new File(['hello world'], 'test.txt', { type: 'text/plain' });
                    addFile(file);
                }}
            >
                Add File
            </button>
            <button
                data-testid="add-file-no-type"
                onClick={() => {
                    const file = new File(['data'], 'unknown.bin', { type: '' });
                    addFile(file);
                }}
            >
                Add No Type
            </button>
            <button data-testid="clear-all" onClick={clearAll}>
                Clear All
            </button>
        </div>
    );
}

describe('AttachmentContext', () => {
    it('throws when useAttachments is used outside AttachmentProvider', () => {
        const spy = jest.spyOn(console, 'error').mockImplementation(() => { });
        expect(() => render(<TestConsumer />)).toThrow(
            'useAttachments must be used within an AttachmentProvider',
        );
        spy.mockRestore();
    });

    it('starts with an empty file list', () => {
        render(
            <AttachmentProvider>
                <TestConsumer />
            </AttachmentProvider>,
        );
        expect(screen.getByTestId('file-count').textContent).toBe('0');
        expect(screen.getByTestId('context-count').textContent).toBe('0');
    });

    it('adds a file with correct properties', async () => {
        render(
            <AttachmentProvider>
                <TestConsumer />
            </AttachmentProvider>,
        );

        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file'));
        });

        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('1');
        });

        // The file list should have one entry
        const listItems = screen.getByTestId('file-list').querySelectorAll('li');
        expect(listItems).toHaveLength(1);

        // Check the file name is correct
        const fileId = listItems[0].getAttribute('data-testid')?.replace('file-', '') || '';
        expect(screen.getByTestId(`name-${fileId}`).textContent).toBe('test.txt');
        expect(screen.getByTestId(`mime-${fileId}`).textContent).toBe('text/plain');
    });

    it('defaults mimeType to application/octet-stream when file type is empty', async () => {
        render(
            <AttachmentProvider>
                <TestConsumer />
            </AttachmentProvider>,
        );

        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file-no-type'));
        });

        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('1');
        });

        const listItems = screen.getByTestId('file-list').querySelectorAll('li');
        const fileId = listItems[0].getAttribute('data-testid')?.replace('file-', '') || '';
        expect(screen.getByTestId(`mime-${fileId}`).textContent).toBe('application/octet-stream');
    });

    it('removes a specific file by id', async () => {
        render(
            <AttachmentProvider>
                <TestConsumer />
            </AttachmentProvider>,
        );

        // Add two files
        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file'));
        });
        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('1');
        });

        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file-no-type'));
        });
        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('2');
        });

        // Remove the first file
        const listItems = screen.getByTestId('file-list').querySelectorAll('li');
        const firstFileId = listItems[0].getAttribute('data-testid')?.replace('file-', '') || '';

        await act(async () => {
            fireEvent.click(screen.getByTestId(`remove-${firstFileId}`));
        });

        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('1');
        });
    });

    it('clears all files', async () => {
        render(
            <AttachmentProvider>
                <TestConsumer />
            </AttachmentProvider>,
        );

        // Add two files
        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file'));
        });
        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('1');
        });

        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file'));
        });
        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('2');
        });

        // Clear all
        await act(async () => {
            fireEvent.click(screen.getByTestId('clear-all'));
        });

        expect(screen.getByTestId('file-count').textContent).toBe('0');
        expect(screen.getByTestId('context-count').textContent).toBe('0');
    });

    it('getContextFiles returns the same files as the files array', async () => {
        render(
            <AttachmentProvider>
                <TestConsumer />
            </AttachmentProvider>,
        );

        await act(async () => {
            fireEvent.click(screen.getByTestId('add-file'));
        });

        await waitFor(() => {
            expect(screen.getByTestId('file-count').textContent).toBe('1');
            expect(screen.getByTestId('context-count').textContent).toBe('1');
        });
    });
});
