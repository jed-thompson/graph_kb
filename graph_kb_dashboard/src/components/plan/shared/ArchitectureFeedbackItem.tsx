'use client';

import { useState, useRef, useCallback } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { MessageSquarePlus, X, Paperclip, Loader2, FileText, ChevronDown, Ban, RotateCcw } from 'lucide-react';
import { uploadPlanDocument, DocumentType } from '@/lib/api/planDocuments';

export interface ItemFeedback {
    note: string;
    fileId: string | null;
    fileName: string | null;
}

interface ArchitectureFeedbackItemProps {
    label: string;
    itemId: string;
    /** Optional description shown below the label */
    description?: string;
    value?: ItemFeedback;
    onChange: (itemId: string, feedback: ItemFeedback) => void;
    variant?: 'secondary' | 'outline';
    /** Optional: render custom content instead of just a label */
    children?: React.ReactNode;
    /** Plan session ID for plan-scoped document uploads. */
    sessionId?: string | null;
    /** Called when the user dismisses this gap. */
    onDismiss?: (itemId: string) => void;
    /** Whether this gap has been dismissed. */
    dismissed?: boolean;
}

export function ArchitectureFeedbackItem({
    label,
    itemId,
    description,
    value,
    onChange,
    children,
    sessionId,
    onDismiss,
    dismissed,
}: ArchitectureFeedbackItemProps) {
    const [expanded, setExpanded] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [uploadError, setUploadError] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);

    const current = value ?? { note: '', fileId: null, fileName: null };

    const uploadFile = useCallback(async (file: File) => {
        if (!sessionId) {
            setUploadError('No session ID available.');
            return;
        }
        setIsUploading(true);
        setUploadError('');
        try {
            const response = await uploadPlanDocument(sessionId, file, DocumentType.Supporting);
            onChange(itemId, { ...current, fileId: response.id, fileName: response.original_filename });
        } catch {
            setUploadError('Failed to upload. Please try again.');
        } finally {
            setIsUploading(false);
        }
    }, [sessionId, itemId, current, onChange]);

    const handleNoteChange = (note: string) => {
        onChange(itemId, { ...current, note });
    };

    const clearFile = () => {
        onChange(itemId, { ...current, fileId: null, fileName: null });
    };

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) uploadFile(file);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        const file = e.dataTransfer.files?.[0];
        if (file) uploadFile(file);
    };

    const hasContent = current.note || current.fileId;

    return (
        <div
            className={`group rounded-lg border border-border/60 bg-card transition-all hover:border-border ${dismissed ? 'opacity-50' : ''}`}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={(e) => e.preventDefault()}
            onDrop={handleDrop}
        >
            {/* Main row */}
            <div className="flex items-start gap-2.5 p-2.5">
                {/* Indicator dot */}
                <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${hasContent ? 'bg-primary' : 'bg-muted-foreground/30'}`} />

                {/* Content */}
                <div className={`flex-1 min-w-0 ${dismissed ? 'line-through' : ''}`}>
                    <div className="flex items-center gap-2 flex-wrap">
                        {children ?? (
                            <span className="text-sm text-foreground leading-snug">{label}</span>
                        )}
                    </div>
                    {description && !dismissed && (
                        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{description}</p>
                    )}
                </div>

                {/* Action buttons */}
                <div className={`flex items-center gap-0.5 shrink-0 transition-opacity ${dismissed ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
                    {/* Dismiss / Restore button */}
                    {onDismiss && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className={`h-6 w-6 ${dismissed ? 'text-muted-foreground hover:text-primary' : 'text-muted-foreground hover:text-destructive'}`}
                            onClick={() => onDismiss(itemId)}
                            aria-label={dismissed ? 'Restore gap' : 'Dismiss gap'}
                        >
                            {dismissed ? <RotateCcw className="h-3.5 w-3.5" /> : <Ban className="h-3.5 w-3.5" />}
                        </Button>
                    )}
                    {/* Feedback toggle */}
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => setExpanded(!expanded)}
                        aria-label={expanded ? 'Collapse feedback' : 'Add feedback'}
                    >
                        {expanded ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                            <MessageSquarePlus className="h-3.5 w-3.5" />
                        )}
                    </Button>
                </div>
            </div>

            {/* Expanded feedback area */}
            {expanded && (
                <div className="border-t border-border/60 p-2.5 space-y-2">
                    <Textarea
                        placeholder="Add feedback or context for this item..."
                        value={current.note}
                        onChange={(e) => handleNoteChange(e.target.value)}
                        className="min-h-[50px] resize-y text-xs"
                        rows={2}
                    />
                    <div className="flex items-center gap-2">
                        <input
                            ref={fileInputRef}
                            type="file"
                            className="hidden"
                            onChange={handleInputChange}
                        />
                        <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={isUploading}
                        >
                            {isUploading ? (
                                <Loader2 className="h-3 w-3 animate-spin mr-1" />
                            ) : (
                                <Paperclip className="h-3 w-3 mr-1" />
                            )}
                            Attach File
                        </Button>
                        {current.fileName && (
                            <div className="flex items-center gap-1 text-xs text-muted-foreground">
                                <FileText className="h-3 w-3" />
                                <span className="truncate max-w-[150px]">{current.fileName}</span>
                                <Button variant="ghost" size="icon" className="h-4 w-4 hover:text-destructive" onClick={clearFile}>
                                    <X className="h-3 w-3" />
                                </Button>
                            </div>
                        )}
                    </div>
                    {uploadError && (
                        <p className="text-xs text-destructive">{uploadError}</p>
                    )}
                </div>
            )}
        </div>
    );
}
