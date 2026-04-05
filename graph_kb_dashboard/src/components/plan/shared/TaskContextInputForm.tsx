'use client';

import { useState } from 'react';

interface TaskContextInputFormProps {
    taskName?: string;
    specSection?: string;
    message?: string;
    isSubmitting: boolean;
    onSubmit: (data: Record<string, unknown>) => void;
    onSkip: () => void;
}

export function TaskContextInputForm({
    taskName,
    specSection,
    message,
    isSubmitting,
    onSubmit,
    onSkip,
}: TaskContextInputFormProps) {
    const [contextUrls, setContextUrls] = useState('');
    const [contextNote, setContextNote] = useState('');

    const handleSubmit = () => {
        onSubmit({
            context_urls: contextUrls,
            context_note: contextNote,
        });
    };

    return (
        <div className="rounded-lg border border-amber-500/20 bg-amber-950/10 p-4 space-y-4">
            <div>
                <h4 className="text-sm font-semibold text-amber-300 mb-1">Context Request</h4>
                {taskName && (
                    <p className="text-xs text-gray-400">
                        Task: <span className="text-gray-300">{taskName}</span>
                        {specSection && <> — Section: <span className="text-gray-300">{specSection}</span></>}
                    </p>
                )}
                {message && <p className="text-xs text-gray-400 mt-1">{message}</p>}
            </div>

            <div className="space-y-3">
                <div>
                    <label htmlFor="context-urls" className="block text-xs font-medium text-gray-300 mb-1">
                        Reference URLs
                    </label>
                    <input
                        id="context-urls"
                        type="text"
                        value={contextUrls}
                        onChange={(e) => setContextUrls(e.target.value)}
                        placeholder="https://docs.example.com/api-reference"
                        disabled={isSubmitting}
                        className="w-full px-3 py-2 rounded-md border border-gray-600 bg-gray-800 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                    />
                </div>
                <div>
                    <label htmlFor="context-note" className="block text-xs font-medium text-gray-300 mb-1">
                        Additional Context
                    </label>
                    <textarea
                        id="context-note"
                        value={contextNote}
                        onChange={(e) => setContextNote(e.target.value)}
                        placeholder="Any notes, requirements, or constraints..."
                        rows={3}
                        disabled={isSubmitting}
                        className="w-full px-3 py-2 rounded-md border border-gray-600 bg-gray-800 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 resize-none"
                    />
                </div>
            </div>

            <div className="flex gap-2">
                <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={isSubmitting}
                    className="px-4 py-2 text-sm font-medium rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
                >
                    Provide Context
                </button>
                <button
                    type="button"
                    onClick={onSkip}
                    disabled={isSubmitting}
                    className="px-4 py-2 text-sm font-medium rounded-md border border-gray-600 text-gray-400 hover:text-gray-300 hover:border-gray-500 disabled:opacity-50 transition-colors"
                >
                    Skip
                </button>
            </div>
        </div>
    );
}
