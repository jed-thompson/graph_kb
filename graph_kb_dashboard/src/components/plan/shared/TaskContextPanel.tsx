'use client';

import { useState } from 'react';

interface TaskContextPanelProps {
    specSection?: string | null;
    specSectionContent?: string | null;
    researchSummary?: string | null;
}

export function TaskContextPanel({
    specSection,
    specSectionContent,
    researchSummary,
}: TaskContextPanelProps) {
    const [activeTab, setActiveTab] = useState<'source' | 'research'>('source');

    const hasSource = specSection && specSectionContent;
    const hasResearch = !!researchSummary;

    if (!hasSource && !hasResearch) return null;

    return (
        <div className="mb-4 rounded-lg border border-blue-500/20 bg-blue-950/10 overflow-hidden">
            {/* Tab bar */}
            <div className="flex border-b border-blue-500/20 bg-blue-950/5">
                {hasSource && (
                    <button
                        type="button"
                        onClick={() => setActiveTab('source')}
                        className={`px-4 py-2 text-sm font-medium transition-colors ${
                            activeTab === 'source'
                                ? 'text-blue-400 border-b-2 border-blue-400'
                                : 'text-gray-400 hover:text-gray-300'
                        }`}
                    >
                        Source Section
                    </button>
                )}
                {hasResearch && (
                    <button
                        type="button"
                        onClick={() => setActiveTab('research')}
                        className={`px-4 py-2 text-sm font-medium transition-colors ${
                            activeTab === 'research'
                                ? 'text-blue-400 border-b-2 border-blue-400'
                                : 'text-gray-400 hover:text-gray-300'
                        }`}
                    >
                        Research
                    </button>
                )}
            </div>

            {/* Content */}
            <div className="p-3 max-h-64 overflow-y-auto">
                {activeTab === 'source' && hasSource && (
                    <div>
                        <h4 className="text-sm font-semibold text-blue-300 mb-2">{specSection}</h4>
                        <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                            {specSectionContent}
                        </pre>
                    </div>
                )}
                {activeTab === 'research' && hasResearch && (
                    <div>
                        <h4 className="text-sm font-semibold text-blue-300 mb-2">Research Findings</h4>
                        <div className="text-xs text-gray-300 whitespace-pre-wrap leading-relaxed">
                            {researchSummary}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
