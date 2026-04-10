'use client';

import React, { useState } from 'react';
import { Eye } from 'lucide-react';
import type { DocumentManifestEntry } from '@/lib/store/planStore';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { PlanDocumentDownload } from '../PlanDocumentDownload';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';

export interface AssemblyDocumentPreviewProps {
    documentPreview?: string;
    manifestEntries?: Array<Record<string, unknown>>;
    specName?: string;
    sessionId?: string | null;
}

export function AssemblyDocumentPreview({
    documentPreview,
    manifestEntries,
    specName,
    sessionId,
}: AssemblyDocumentPreviewProps) {
    const [previewOpen, setPreviewOpen] = useState(false);

    // Unwrap JSON envelope if the stored preview is a JSON wrapper
    const resolvedPreview = React.useMemo(() => {
        if (!documentPreview) return documentPreview;
        const trimmed = documentPreview.trim();
        if (!trimmed.startsWith('{')) return documentPreview;
        try {
            const parsed = JSON.parse(trimmed);
            if (parsed && typeof parsed === 'object' && typeof parsed.assembled_document === 'string' && parsed.assembled_document.length > 50) {
                return parsed.assembled_document as string;
            }
        } catch { /* not JSON */ }
        return documentPreview;
    }, [documentPreview]);

    // Convert backend manifest entries to frontend DocumentManifestEntry format
    const downloadEntries: DocumentManifestEntry[] | undefined = manifestEntries?.map(e => ({
        taskId: (e.task_id as string) || '',
        taskName: (e.task_name as string) || '',
        specSection: (e.spec_section as string) || '',
        filename: `${(e.spec_section as string) || (e.task_id as string) || 'section'}.md`,
        status: (e.status as DocumentManifestEntry['status']) || 'draft',
        tokenCount: (e.token_count as number) || 0,
        downloadUrl: (e.download_url as string) || '',
        errorMessage: e.error_message as string | undefined,
    }));

    return (
        <div className="space-y-3 border-t pt-4">
            {/* Section downloads (always visible) */}
            {downloadEntries && downloadEntries.length > 0 && (
                <PlanDocumentDownload
                    sessionId={sessionId}
                    manifestEntries={downloadEntries}
                    specName={specName}
                    isPreview
                />
            )}

            {/* Full document preview — opens as overlay */}
            {resolvedPreview && (
                <>
                    <button
                        type="button"
                        onClick={() => setPreviewOpen(true)}
                        className="flex items-center gap-2 text-sm font-medium text-foreground hover:text-foreground/80 transition-colors w-full border-t pt-3"
                    >
                        <Eye className="h-4 w-4" />
                        <span>Full Document Preview</span>
                    </button>

                    <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
                        <DialogContent className="max-w-4xl w-[90vw] h-[85vh] flex flex-col p-0">
                            <DialogHeader className="px-6 pt-6 pb-3 border-b shrink-0">
                                <DialogTitle>{specName || 'Document Preview'}</DialogTitle>
                            </DialogHeader>
                            <div className="flex-1 overflow-y-auto px-6 py-4">
                                <MarkdownRenderer content={resolvedPreview} />
                            </div>
                        </DialogContent>
                    </Dialog>
                </>
            )}
        </div>
    );
}
