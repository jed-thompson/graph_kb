'use client';

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Loader2, Upload, X, FileText, Search } from 'lucide-react';
import { uploadPlanDocument, DocumentType } from '@/lib/api/planDocuments';
import { listDocuments } from '@/lib/api/documents';
import type { DocumentResponse } from '@/lib/types/api';
import type { PhaseField } from '@shared/websocket-events';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { fuzzyMatch } from '@/lib/utils/fuzzyMatch';

export interface FileUploadFieldProps {
    field: PhaseField;
    value: unknown;
    error?: string;
    onChange: (value: unknown) => void;
    /** Plan session ID — required for plan-scoped document uploads. */
    sessionId?: string | null;
}

export function FileUploadField({ field, value, error, onChange, sessionId }: FileUploadFieldProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [fileName, setFileName] = useState('');
    const [isDragging, setIsDragging] = useState(false);
    const [uploadError, setUploadError] = useState('');

    // Active tab state
    const [activeTab, setActiveTab] = useState<string>('upload');

    // Existing Selection State
    const [existingDocs, setExistingDocs] = useState<DocumentResponse[]>([]);
    const [isFetchingDocs, setIsFetchingDocs] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    // Text Snippet State
    const [textSnippet, setTextSnippet] = useState('');

    const handleFileSelect = useCallback(async (file: File) => {
        const allowedTypes = [
            'application/pdf', 'text/markdown', 'text/plain', 'text/yaml',
            'application/x-yaml', 'application/json',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
        ];

        if (!allowedTypes.includes(file.type) && !file.name.match(/\.(md|ya?ml|json)$/i)) {
            setUploadError('Invalid file type. Supports PDF, Markdown, Word, YAML, JSON.');
            return;
        }

        if (!sessionId) {
            setUploadError('No session ID available. Cannot upload document.');
            return;
        }

        setIsUploading(true);
        setUploadError('');

        try {
            const role = field.id?.includes('primary') ? DocumentType.Primary : DocumentType.Supporting;
            const response = await uploadPlanDocument(sessionId, file, role);
            onChange(response.id);
            setFileName(response.original_filename);
        } catch {
            setUploadError('Failed to upload. Please try again.');
        } finally {
            setIsUploading(false);
        }
    }, [onChange, sessionId]);

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) handleFileSelect(file);
    };

    const clearFile = () => {
        onChange('');
        setFileName('');
        if (fileInputRef.current) fileInputRef.current.value = '';
        setTextSnippet('');
    };

    // Load Existing Docs
    useEffect(() => {
        if (activeTab === 'existing' && existingDocs.length === 0) {
            setIsFetchingDocs(true);
            listDocuments({ limit: 100 })
                .then(res => setExistingDocs(res.documents || []))
                .catch(err => console.error('Failed to fetch existing documents:', err))
                .finally(() => setIsFetchingDocs(false));
        }
    }, [activeTab, existingDocs.length]);

    const filteredDocs = useMemo(() => {
        if (!searchQuery) return existingDocs;
        return existingDocs.filter(d => fuzzyMatch(searchQuery, d.filename));
    }, [existingDocs, searchQuery]);

    const handleSelectExisting = (doc: DocumentResponse) => {
        onChange(doc.id);
        setFileName(doc.filename);
    };

    const handleSaveTextSnippet = async () => {
        if (!textSnippet.trim() || !sessionId) return;
        setIsUploading(true);
        setUploadError('');
        try {
            const blob = new File([textSnippet], `Snippet_${Date.now()}.txt`, { type: 'text/plain' });
            const role = field.id?.includes('primary') ? DocumentType.Primary : DocumentType.Supporting;
            const response = await uploadPlanDocument(sessionId, blob, role);
            onChange(response.id);
            setFileName(response.original_filename);
        } catch {
            setUploadError('Failed to save text snippet. Please try again.');
        } finally {
            setIsUploading(false);
        }
    };

    return (
        <div className="space-y-2">
            <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>

            {value && fileName ? (
                <div className="border border-border rounded-lg p-3 flex items-center justify-between bg-muted/30">
                    <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-green-500" />
                        <span className="text-sm font-medium">{fileName}</span>
                    </div>
                    <Button variant="ghost" size="sm" onClick={clearFile}>
                        <X className="h-4 w-4" />
                    </Button>
                </div>
            ) : (
                <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
                    <TabsList className="grid w-full grid-cols-3">
                        <TabsTrigger value="upload">Upload</TabsTrigger>
                        <TabsTrigger value="existing">Select Existing</TabsTrigger>
                        <TabsTrigger value="text">Text Snippet</TabsTrigger>
                    </TabsList>

                    <TabsContent value="upload" className="pt-2">
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".pdf,.md,.markdown,.doc,.docx,.txt,.yaml,.yml,.json"
                            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileSelect(f); }}
                            className="hidden"
                        />
                        <div
                            onClick={() => fileInputRef.current?.click()}
                            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                            onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
                            onDrop={handleDrop}
                            className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${isDragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}`}
                        >
                            {isUploading ? (
                                <>
                                    <Loader2 className="h-6 w-6 mx-auto text-primary animate-spin mb-2" />
                                    <p className="text-sm text-muted-foreground">Uploading...</p>
                                </>
                            ) : (
                                <>
                                    <Upload className="h-6 w-6 mx-auto text-muted-foreground mb-2" />
                                    <p className="text-sm text-muted-foreground">
                                        Drag and drop a file here, or click to browse
                                    </p>
                                    <p className="text-xs text-muted-foreground mt-1">
                                        PDF, Markdown, Word, YAML, JSON
                                    </p>
                                </>
                            )}
                        </div>
                    </TabsContent>

                    <TabsContent value="existing" className="pt-2 space-y-3 border rounded-lg p-3 bg-card">
                        <div className="relative">
                            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                            <Input
                                placeholder="Search existing documents..."
                                className="pl-9 h-9"
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                            />
                        </div>
                        <div className="max-h-48 overflow-y-auto space-y-1 pr-1">
                            {isFetchingDocs ? (
                                <div className="flex justify-center p-4">
                                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                </div>
                            ) : filteredDocs.length > 0 ? (
                                filteredDocs.map((doc) => (
                                    <div
                                        key={doc.id}
                                        onClick={() => handleSelectExisting(doc)}
                                        className="flex items-center gap-2 p-2 rounded-md hover:bg-muted cursor-pointer transition-colors border border-transparent hover:border-border"
                                    >
                                        <FileText className="h-4 w-4 shrink-0 text-primary/70" />
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm font-medium truncate">{doc.filename}</p>
                                            {doc.category && <p className="text-xs text-muted-foreground">{doc.category}</p>}
                                        </div>
                                    </div>
                                ))
                            ) : (
                                <p className="text-sm text-center text-muted-foreground p-4">
                                    No documents found.
                                </p>
                            )}
                        </div>
                    </TabsContent>

                    <TabsContent value="text" className="pt-2 space-y-2">
                        <Textarea
                            placeholder="Paste your requirements or context here..."
                            rows={6}
                            value={textSnippet}
                            onChange={(e) => setTextSnippet(e.target.value)}
                            className="resize-none"
                            disabled={isUploading}
                        />
                        <div className="flex justify-end">
                            <Button
                                type="button"
                                size="sm"
                                onClick={handleSaveTextSnippet}
                                disabled={!textSnippet.trim() || isUploading}
                            >
                                {isUploading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                                Save Snippet
                            </Button>
                        </div>
                    </TabsContent>
                </Tabs>
            )}

            {(error || uploadError) && (
                <p className="text-sm text-red-500">{error || uploadError}</p>
            )}
        </div>
    );
}
