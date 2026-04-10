'use client';

import React from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Loader2, ChevronDown, ChevronUp, Upload, X, FileText, MessageSquarePlus } from 'lucide-react';
import { ACCEPTED_EXTENSIONS } from '@/hooks/useFileUpload';

interface UploadedFile {
    id: string;
    filename: string;
}

export interface ApprovalFeedbackInputProps {
    showContextInput: boolean;
    onToggleContextInput: () => void;
    contextText: string;
    onContextTextChange: (value: string) => void;
    uploadedFile: UploadedFile | null;
    isUploading: boolean;
    fileInputRef: React.RefObject<HTMLInputElement>;
    onFileInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    onRemoveFile: (fileId: string) => void;
}

export function ApprovalFeedbackInput({
    showContextInput,
    onToggleContextInput,
    contextText,
    onContextTextChange,
    uploadedFile,
    isUploading,
    fileInputRef,
    onFileInputChange,
    onRemoveFile,
}: ApprovalFeedbackInputProps) {
    return (
        <div className="border-t pt-3">
            <button
                type="button"
                onClick={onToggleContextInput}
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
            >
                <MessageSquarePlus className="h-4 w-4" />
                <span>Provide Additional Context</span>
                {showContextInput
                    ? <ChevronUp className="h-4 w-4 ml-auto" />
                    : <ChevronDown className="h-4 w-4 ml-auto" />}
            </button>

            {showContextInput && (
                <div className="mt-3 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                    <Textarea
                        placeholder="Add context, requirements, or reference material to help the next phase..."
                        value={contextText}
                        onChange={(e) => onContextTextChange(e.target.value)}
                        className="min-h-[80px] resize-y"
                    />
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept={ACCEPTED_EXTENSIONS}
                        onChange={onFileInputChange}
                        className="hidden"
                    />
                    {uploadedFile ? (
                        <div className="border border-border rounded-md p-2 flex items-center gap-2 bg-muted/30">
                            <FileText className="h-4 w-4 text-green-500 shrink-0" />
                            <span className="text-xs font-medium truncate">{uploadedFile.filename}</span>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 ml-auto shrink-0"
                                onClick={() => onRemoveFile(uploadedFile.id)}
                            >
                                <X className="h-3 w-3" />
                            </Button>
                        </div>
                    ) : (
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="text-xs"
                            disabled={isUploading}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            {isUploading
                                ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                                : <Upload className="h-3.5 w-3.5 mr-1.5" />}
                            {isUploading ? 'Uploading...' : 'Attach File'}
                        </Button>
                    )}
                </div>
            )}
        </div>
    );
}
