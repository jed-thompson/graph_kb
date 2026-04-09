'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { CollapsibleCard } from '@/components/ui/CollapsibleCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    Globe,
    FileText,
    MessageSquare,
    Eye,
    Loader2,
    X,
} from 'lucide-react';
import { downloadPlanDocument } from '@/lib/api/planDocuments';
import { usePlanDocumentFilenames } from '@/hooks/usePlanDocumentFilenames';
import { getDocument } from '@/lib/api/documents';
import { getPlanArtifact } from '@/lib/api/planArtifacts';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';

// ── Types ──────────────────────────────────────────────────────────────

export interface ContextRound {
    round_number?: number;
    prompt_type?: string;
    user_input?: string;
    uploaded_docs?: string[];
    selected_template?: string | null;
    timestamp?: string;
}

/** Metadata for a scraped URL stored as a document. */
export interface ExtractedUrl {
    url: string;
    /** Document ID when stored via SpecDocumentRepository (preferred). */
    document_id?: string;
    /** Legacy artifact key (fallback for older sessions). */
    artifact_key?: string;
    summary?: string;
    size_bytes?: number;
}

export interface ContextItems {
    extracted_urls?: string[] | ExtractedUrl[];
    rounds?: ContextRound[];
    primary_document_id?: string;
    supporting_doc_ids?: string[];
    user_explanation?: string;
}

interface ContextItemsPanelProps {
    contextItems?: ContextItems;
    /** Plan session ID for retrieving blob-stored artifacts on demand. */
    sessionId?: string | null;
}

// ── Document Overlay ───────────────────────────────────────────────────

interface OverlayDoc {
    filename: string;
    content: string;
    loading?: boolean;
    error?: string;
}

function DocumentViewOverlay({
    doc,
    onClose,
}: {
    doc: OverlayDoc | null;
    onClose: () => void;
}) {
    if (!doc) return null;

    return (
        <>
            <div
                className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
                onClick={onClose}
            />
            <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none">
                <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-[95vw] max-w-4xl max-h-[85vh] flex flex-col relative pointer-events-auto">
                    <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
                        <div className="flex items-center gap-3">
                            <FileText className="h-5 w-5 text-primary" />
                            <h2 className="text-lg font-semibold">{doc.filename}</h2>
                        </div>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={onClose}
                            className="text-gray-400 hover:text-gray-600"
                        >
                            <X className="h-5 w-5" />
                        </Button>
                    </div>
                    <div className="flex-1 overflow-auto p-6">
                        {doc.loading ? (
                            <div className="flex items-center justify-center py-12">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                <span className="ml-2 text-sm text-muted-foreground">
                                    Loading document...
                                </span>
                            </div>
                        ) : doc.error ? (
                            <div className="flex flex-col items-center justify-center py-12 text-center">
                                <div className="text-destructive mb-3">
                                    <FileText className="h-8 w-8 mx-auto opacity-50" />
                                </div>
                                <p className="text-sm font-medium text-destructive mb-1">
                                    Failed to load document
                                </p>
                                <p className="text-xs text-muted-foreground max-w-md break-all">
                                    {doc.error}
                                </p>
                            </div>
                        ) : (
                            <div className="text-sm bg-gray-50 dark:bg-gray-800 p-6 rounded-lg leading-relaxed">
                                <MarkdownRenderer content={doc.content || 'No content available'} />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </>
    );
}

// ── Context Item Row ───────────────────────────────────────────────────

interface ContextDocItem {
    id: string;
    label: string;
}

interface ContextTextItem {
    id: string;
    label: string;
    content: string;
    icon?: React.ReactNode;
}

function ContextDocRow({ item, onView }: { item: ContextDocItem; onView: () => void }) {
    return (
        <button
            type="button"
            onClick={onView}
            className="w-full flex items-center justify-between gap-2 py-2 px-3 rounded-lg border border-border/50 hover:border-border hover:bg-muted/30 transition-colors group text-left"
        >
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                <FileText className="h-4 w-4 text-primary/70 flex-shrink-0" />
                <span className="text-sm truncate">{item.label}</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                <Eye className="h-3.5 w-3.5" />
                <span>View</span>
            </div>
        </button>
    );
}

function ContextTextRow({ item, onView }: { item: ContextTextItem; onView: () => void }) {
    const preview = item.content.length > 120 ? item.content.slice(0, 120) + '…' : item.content;
    return (
        <button
            type="button"
            onClick={onView}
            className="w-full text-left py-2 px-3 rounded-lg border border-border/50 hover:border-border hover:bg-muted/30 transition-colors group"
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    {item.icon || <MessageSquare className="h-4 w-4 text-primary/70 flex-shrink-0" />}
                    <span className="text-sm font-medium truncate">{item.label}</span>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <Eye className="h-3.5 w-3.5" />
                    <span>View</span>
                </div>
            </div>
            {item.content && (
                <p className="text-xs text-muted-foreground mt-1 leading-relaxed line-clamp-2 ml-[30px]">
                    {preview}
                </p>
            )}
        </button>
    );
}

// ── Main Panel ─────────────────────────────────────────────────────────

export function ContextItemsPanel({ contextItems, sessionId }: ContextItemsPanelProps) {
    const [overlayDoc, setOverlayDoc] = useState<OverlayDoc | null>(null);
    const [mounted, setMounted] = useState(false);

    // SSR guard: document.body is not available during server-side rendering
    useEffect(() => {
        setMounted(true);
    }, []);

    // Stable keys derived from document IDs — avoids re-fetching on every
    // contextItems object reference change (which happens on every re-render).
    const primaryDocId = contextItems?.primary_document_id ?? null;

    const filenameMap = usePlanDocumentFilenames(
        sessionId,
        primaryDocId,
        contextItems?.supporting_doc_ids ?? [],
    );

    if (!contextItems || Object.keys(contextItems).length === 0) return null;

    // Normalize URLs to ExtractedUrl format
    const rawUrls = contextItems.extracted_urls ?? [];
    const urlItems: ExtractedUrl[] = rawUrls.map(u =>
        typeof u === 'string' ? { url: u } : u,
    );

    // Document IDs that belong to scraped URLs (rendered in their own section)
    const urlDocIds = new Set(urlItems.map(u => u.document_id).filter(Boolean));

    // Collect all document references, excluding scraped URL docs
    const allDocIds: ContextDocItem[] = [];
    const primaryId = contextItems.primary_document_id;

    /** Generate a human-readable label for a document ID */
    const getDocLabel = (id: string, index: number, isPrimary: boolean): string => {
        if (filenameMap[id]) return filenameMap[id];
        // Check if it looks like a UUID — show friendly name instead
        const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
        if (isUuid) {
            return isPrimary ? 'Primary Document' : `Document ${index + 1}`;
        }
        return id;
    };

    if (primaryId && !urlDocIds.has(primaryId)) {
        allDocIds.push({ id: primaryId, label: getDocLabel(primaryId, 0, true) });
    }
    const supportingIds = contextItems.supporting_doc_ids ?? [];
    for (let i = 0; i < supportingIds.length; i++) {
        const id = supportingIds[i];
        if (!urlDocIds.has(id)) {
            allDocIds.push({ id, label: getDocLabel(id, i, false) });
        }
    }
    // Collect uploaded docs from rounds
    const rounds = contextItems.rounds ?? [];
    for (const round of rounds) {
        const docs = round.uploaded_docs ?? [];
        for (let i = 0; i < docs.length; i++) {
            const docId = docs[i];
            if (!allDocIds.find(d => d.id === docId) && !urlDocIds.has(docId)) {
                allDocIds.push({ id: docId, label: getDocLabel(docId, allDocIds.length, false) });
            }
        }
    }

    const userExplanation = contextItems.user_explanation;

    // Collect unique user inputs from rounds
    const userInputs = rounds
        .filter(r => r.user_input && r.user_input.trim().length > 0)
        .map((r, i) => ({
            round: r.round_number ?? i + 1,
            text: r.user_input!,
        }));

    const handleViewDocument = async (docId: string) => {
        const initialFilename = filenameMap[docId] || docId;
        setOverlayDoc({ filename: initialFilename, content: '', loading: true });
        const isPdf = initialFilename.toLowerCase().endsWith('.pdf');
        try {
            // PDFs skip the raw download (returns binary) and use getDocument
            // which does server-side pypdf text extraction.
            if (sessionId && !isPdf) {
                try {
                    const content = await downloadPlanDocument(sessionId, docId);
                    setOverlayDoc({ filename: initialFilename, content });
                    return;
                } catch {
                    // Existing library documents are not plan-scoped uploads.
                    // Fall through to the global documents API.
                }
            }

            const document = await getDocument(docId);
            setOverlayDoc({
                filename: document.filename || initialFilename,
                content: document.content || 'No content available',
            });
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Failed to load document content.';
            setOverlayDoc({ filename: initialFilename, content: '', error: msg });
        }
    };

    const handleViewUrlArtifact = async (item: ExtractedUrl) => {
        const filename = item.url;
        setOverlayDoc({ filename, content: '', loading: true });
        if (item.document_id && sessionId) {
            try {
                const content = await downloadPlanDocument(sessionId, item.document_id);
                setOverlayDoc({ filename, content });
            } catch (err) {
                // Document endpoint failed — try artifact endpoint as fallback
                if (item.artifact_key && sessionId) {
                    try {
                        const result = await getPlanArtifact(sessionId, item.artifact_key);
                        setOverlayDoc({ filename, content: result.content });
                    } catch (artErr) {
                        const msg = artErr instanceof Error ? artErr.message : 'Failed to load scraped content via artifact endpoint.';
                        setOverlayDoc({ filename, content: '', error: msg });
                    }
                } else {
                    const msg = err instanceof Error ? err.message : 'Failed to load scraped content.';
                    setOverlayDoc({ filename, content: '', error: msg });
                }
            }
        } else if (item.artifact_key && sessionId) {
            try {
                const result = await getPlanArtifact(sessionId, item.artifact_key);
                setOverlayDoc({ filename, content: result.content });
            } catch (err) {
                const msg = err instanceof Error ? err.message : 'Failed to load scraped content.';
                setOverlayDoc({ filename, content: '', error: msg });
            }
        } else {
            setOverlayDoc({ filename, content: '', error: `No document ID or artifact key for this URL. Session: ${sessionId || 'none'}` });
        }
    };

    const totalItems =
        urlItems.length +
        allDocIds.length +
        userInputs.length +
        (userExplanation ? 1 : 0);

    return (
        <>
            <CollapsibleCard
                title="Gathered Context"
                subtitle="URLs, documents, and inputs collected during context gathering"
                icon={<Globe className="h-4 w-4" />}
                badge={<Badge variant="secondary">{totalItems} items</Badge>}
                defaultExpanded={true}
                variant="info"
                size="sm"
            >
                <div className="space-y-3">
                    {/* Scraped URLs */}
                    {urlItems.length > 0 && (
                        <div>
                            <div className="flex items-center gap-2 mb-1.5">
                                <Globe className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                    Scraped URLs
                                </span>
                                <Badge variant="outline" className="text-[10px] h-4 px-1">
                                    {urlItems.length}
                                </Badge>
                            </div>
                            <div className="space-y-1.5">
                                {urlItems.map((item, i) => (
                                    <ContextDocRow
                                        key={i}
                                        item={{ id: item.document_id ?? item.artifact_key ?? `url-${i}`, label: item.url }}
                                        onView={() => handleViewUrlArtifact(item)}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Documents */}
                    {allDocIds.length > 0 && (
                        <div>
                            <div className="flex items-center gap-2 mb-1.5">
                                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                    Documents
                                </span>
                                <Badge variant="outline" className="text-[10px] h-4 px-1">
                                    {allDocIds.length}
                                </Badge>
                            </div>
                            <div className="space-y-1.5">
                                {allDocIds.map(doc => (
                                    <ContextDocRow
                                        key={doc.id}
                                        item={doc}
                                        onView={() => handleViewDocument(doc.id)}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* User Context */}
                    {userExplanation && (
                        <div>
                            <div className="flex items-center gap-2 mb-1.5">
                                <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                    User Context
                                </span>
                                <Badge variant="outline" className="text-[10px] h-4 px-1">
                                    1
                                </Badge>
                            </div>
                            <div className="space-y-1.5">
                                <ContextTextRow
                                    item={{ id: 'user-explanation', label: 'User description', content: userExplanation }}
                                    onView={() => setOverlayDoc({ filename: 'User Context', content: userExplanation })}
                                />
                            </div>
                        </div>
                    )}

                    {/* User Inputs from Rounds */}
                    {userInputs.length > 0 && (
                        <div>
                            <div className="flex items-center gap-2 mb-1.5">
                                <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                    Round Inputs
                                </span>
                                <Badge variant="outline" className="text-[10px] h-4 px-1">
                                    {userInputs.length}
                                </Badge>
                            </div>
                            <div className="space-y-1.5">
                                {userInputs.map(input => (
                                    <ContextTextRow
                                        key={input.round}
                                        item={{
                                            id: `round-${input.round}`,
                                            label: `Round ${input.round}`,
                                            content: input.text,
                                            icon: <span className="text-[10px] text-muted-foreground font-medium w-16 flex-shrink-0">R{input.round}</span>,
                                        }}
                                        onView={() => setOverlayDoc({ filename: `Round ${input.round}`, content: input.text })}
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </CollapsibleCard>

            {/* Document overlay — portaled to body to avoid CSS stacking context issues */}
            {mounted && createPortal(
                <DocumentViewOverlay
                    doc={overlayDoc}
                    onClose={() => setOverlayDoc(null)}
                />,
                document.body,
            )}
        </>
    );
}
