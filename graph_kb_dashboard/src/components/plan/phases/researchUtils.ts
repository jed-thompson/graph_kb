/**
 * Utility functions for extracting and normalizing research phase data.
 * Extracted from ResearchPhase.tsx to support reuse and testability.
 */

export interface ResearchData {
    contextCards: Record<string, unknown>[];
    gaps: Record<string, unknown>[];
    findings: Record<string, unknown> | null;
    progress: { percent: number; phase: string };
}

const EMPTY_RESEARCH_DATA: ResearchData = {
    contextCards: [],
    gaps: [],
    findings: null,
    progress: { percent: 0, phase: 'idle' },
};

/**
 * Extract and normalize research data from a phase result object.
 * Handles both camelCase and snake_case field names from the backend.
 */
export function extractResearchData(
    result: Record<string, unknown> | undefined,
): ResearchData {
    if (!result) return { ...EMPTY_RESEARCH_DATA };

    const contextCards = Array.isArray(result.context_cards)
        ? (result.context_cards as Record<string, unknown>[])
        : Array.isArray(result.contextCards)
            ? (result.contextCards as Record<string, unknown>[])
            : [];

    const gaps = Array.isArray(result.gaps)
        ? (result.gaps as Record<string, unknown>[])
        : Array.isArray(result.knowledge_gaps)
            ? (result.knowledge_gaps as Record<string, unknown>[])
            : [];

    const findings = (result.findings || null) as Record<string, unknown> | null;
    const progress = (result.progress || { percent: 0, phase: 'idle' }) as {
        percent: number;
        phase: string;
    };

    return { contextCards, gaps, findings, progress };
}
