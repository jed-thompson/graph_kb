'use client';

import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Card } from '@/components/ui/card';
import { Loader2, Upload, X, FileText, File, FileCode, Edit2, Folder, Eye } from 'lucide-react';
import { useFileUpload, ACCEPTED_EXTENSIONS, type UploadWithMetadataOptions } from '@/hooks/useFileUpload';
import { useResearchStore } from '@/lib/store/researchStore';
import type { UploadedDocument } from '@/lib/types/research';
import { CategoryUploadModal } from '@/components/documents/CategoryUploadModal';
import { apiClient } from '@/lib/api/client';

interface DocumentUploaderProps {
  disabled?: boolean;
}

/**
 * DocumentUploader - Drag & drop file upload for research documents.
 * Uses the shared useFileUpload hook for consistent upload behavior.
 * Shows a category selection modal before uploading.
 */
export function DocumentUploader({ disabled = false }: DocumentUploaderProps) {
  const { addDocument, removeDocument, uploadedDocuments } = useResearchStore();
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [editingDoc, setEditingDoc] = useState<UploadedDocument | null>(null);
  const [existingCategories, setExistingCategories] = useState<string[]>([]);
  const [existingParents, setExistingParents] = useState<string[]>([]);
  const [isUpdating, setIsUpdating] = useState(false);

  // Document viewer state
  const [viewingDoc, setViewingDoc] = useState<UploadedDocument | null>(null);
  const [documentContent, setDocumentContent] = useState<string>('');
  const [isLoadingContent, setIsLoadingContent] = useState(false);

  const {
    isUploading,
    isDragging,
    error: uploadError,
    fileInputRef,
    handleDragOver,
    handleDragLeave,
    uploadWithMetadata,
    validateFile,
    clearError,
  } = useFileUpload({
    disabled,
    storeInternally: false,
  });

  // Fetch existing categories and parents from the server
  useEffect(() => {
    const fetchFilterOptions = async () => {
      try {
        const response = await apiClient.get<{
          categories: string[];
          parents: string[];
        }>('/docs/filter-options');
        setExistingCategories(response.categories || []);
        setExistingParents(response.parents || []);
      } catch (err) {
        console.error('Failed to fetch filter options:', err);
        // Don't block - use empty arrays
      }
    };
    fetchFilterOptions();
  }, []);

  const getFileIcon = (mimeType: string) => {
    if (mimeType.includes('pdf')) return FileText;
    if (mimeType.includes('json') || mimeType.includes('yaml')) return FileCode;
    return File;
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const clearFile = (docId: string) => {
    removeDocument(docId);
  };

  // Handle file selection - show modal instead of immediate upload
  const handleFileSelect = useCallback((files: FileList | File[]) => {
    if (disabled || isUploading) return;

    const fileArray = Array.from(files);
    const validFiles: File[] = [];

    for (const file of fileArray) {
      const validationError = validateFile(file);
      if (!validationError) {
        validFiles.push(file);
      }
    }

    if (validFiles.length > 0) {
      setPendingFiles(validFiles);
      setShowCategoryModal(true);
      clearError();
    }
  }, [disabled, isUploading, validateFile, clearError]);

  // Handle drop event
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    handleDragLeave(e);
    if (disabled || isUploading) return;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files);
    }
  }, [disabled, isUploading, handleFileSelect, handleDragLeave]);

  // Handle input change
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelect(e.target.files);
    }
    // Reset input so same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [handleFileSelect]);

  // Handle category modal upload
  const handleCategoryUpload = useCallback(async (options: UploadWithMetadataOptions) => {
    if (pendingFiles.length === 0) return;

    setIsUpdating(true);
    let successCount = 0;

    for (const file of pendingFiles) {
      const uploadedFile = await uploadWithMetadata(file, options);
      if (uploadedFile) {
        const doc: UploadedDocument = {
          id: uploadedFile.id,
          filename: uploadedFile.filename,
          size: uploadedFile.size || 0,
          mimeType: uploadedFile.mimeType || '',
          uploadedAt: new Date().toISOString(),
          category: options.category,
          parent: options.parent,
          indexedForSearch: options.indexForSearch,
        };
        addDocument(doc);
        successCount++;
      }
    }

    setIsUpdating(false);
    setPendingFiles([]);
    setShowCategoryModal(false);

    // Refresh categories/parents list
    if (options.category && !existingCategories.includes(options.category)) {
      setExistingCategories(prev => [...prev, options.category!]);
    }
    if (options.parent && !existingParents.includes(options.parent)) {
      setExistingParents(prev => [...prev, options.parent!]);
    }
  }, [pendingFiles, uploadWithMetadata, addDocument, existingCategories, existingParents]);

  // Handle category modal cancel
  const handleCategoryCancel = useCallback(() => {
    setPendingFiles([]);
    setShowCategoryModal(false);
  }, []);

  // Handle edit category for existing document
  const handleEditCategory = useCallback((doc: UploadedDocument) => {
    setEditingDoc(doc);
    setShowCategoryModal(true);
  }, []);

  // Handle category update for existing document
  const handleCategoryUpdate = useCallback(async (options: UploadWithMetadataOptions) => {
    if (!editingDoc) return;

    setIsUpdating(true);
    try {
      // Update document metadata via API
      await apiClient.patch(`/docs/${editingDoc.id}`, {
        category: options.category,
        parent: options.parent,
        index_for_search: options.indexForSearch,
      });

      // Update local store
      const updatedDoc: UploadedDocument = {
        ...editingDoc,
        category: options.category,
        parent: options.parent,
        indexedForSearch: options.indexForSearch,
      };

      // Remove and re-add to update the document in store
      removeDocument(editingDoc.id);
      addDocument(updatedDoc);

      // Refresh categories/parents list
      if (options.category && !existingCategories.includes(options.category)) {
        setExistingCategories(prev => [...prev, options.category!]);
      }
      if (options.parent && !existingParents.includes(options.parent)) {
        setExistingParents(prev => [...prev, options.parent!]);
      }
    } catch (err) {
      console.error('Failed to update document category:', err);
    } finally {
      setIsUpdating(false);
      setEditingDoc(null);
      setShowCategoryModal(false);
    }
  }, [editingDoc, removeDocument, addDocument, existingCategories, existingParents]);

  // Handle edit modal cancel
  const handleEditCancel = useCallback(() => {
    setEditingDoc(null);
    setShowCategoryModal(false);
  }, []);

  const isLoading = isUploading || isUpdating;

  // Handle viewing document content
  const handleViewDocument = useCallback(async (doc: UploadedDocument) => {
    setViewingDoc(doc);
    setIsLoadingContent(true);
    setDocumentContent('');

    try {
      const response = await apiClient.get<{ content: string }>(`/docs/${doc.id}/content`);
      setDocumentContent(response.content || 'No content available');
    } catch (err) {
      console.error('Failed to fetch document content:', err);
      setDocumentContent('Failed to load document content');
    } finally {
      setIsLoadingContent(false);
    }
  }, []);

  const handleCloseViewer = useCallback(() => {
    setViewingDoc(null);
    setDocumentContent('');
  }, []);

  return (
    <div className="space-y-3">
      <Label className="flex items-center gap-2">
        <Upload className="h-4 w-4" />
        Documents for Context
      </Label>

      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS}
        onChange={handleInputChange}
        className="hidden"
        disabled={disabled || isLoading}
        multiple
      />

      {/* Drop Zone */}
      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
          isDragging
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50'
        } ${disabled || isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        {isLoading ? (
          <>
            <Loader2 className="h-6 w-6 mx-auto text-primary animate-spin mb-2" />
            <p className="text-sm text-muted-foreground">
              {isUpdating ? 'Updating...' : 'Uploading...'}
            </p>
          </>
        ) : (
          <>
            <Upload className="h-6 w-6 mx-auto text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">
              Drag and drop files here, or click to browse
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              PDF, Markdown, Word, YAML, JSON, TXT (max 10MB)
            </p>
          </>
        )}
      </div>

      {uploadError && <p className="text-sm text-red-500">{uploadError}</p>}

      {/* Category Selection Modal */}
      <CategoryUploadModal
        open={showCategoryModal}
        onOpenChange={setShowCategoryModal}
        files={editingDoc ? [{ name: editingDoc.filename }] : pendingFiles}
        existingCategories={existingCategories}
        existingParents={existingParents}
        onUpload={editingDoc ? handleCategoryUpdate : handleCategoryUpload}
        onCancel={editingDoc ? handleEditCancel : handleCategoryCancel}
      />

      {/* Uploaded Files List */}
      {uploadedDocuments.length > 0 && (
        <div className="space-y-2">
          {uploadedDocuments.map((doc) => {
            const Icon = getFileIcon(doc.mimeType);
            return (
              <Card
                key={doc.id}
                className="p-3 flex items-center justify-between bg-muted/30"
              >
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <Icon className="h-5 w-5 text-green-500 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{doc.filename}</p>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{formatFileSize(doc.size)}</span>
                      {doc.category && (
                        <span className="flex items-center gap-1">
                          <Folder className="h-3 w-3" />
                          {doc.category}
                        </span>
                      )}
                      {!doc.category && (
                        <span className="text-amber-600 dark:text-amber-500">
                          Uncategorized
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleViewDocument(doc)}
                    disabled={disabled || isLoading}
                    title="View document"
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleEditCategory(doc)}
                    disabled={disabled || isLoading}
                    title="Edit category"
                  >
                    <Edit2 className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => clearFile(doc.id)}
                    disabled={disabled}
                    title="Remove document"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Document Viewer Overlay */}
      {viewingDoc && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={handleCloseViewer}
        >
          <div
            className="bg-background border rounded-lg shadow-lg max-w-3xl w-full max-h-[80vh] m-4 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-semibold truncate">{viewingDoc.filename}</h3>
              <Button variant="ghost" size="sm" onClick={handleCloseViewer}>
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {isLoadingContent ? (
                <div className="flex items-center justify-center h-32">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <pre className="text-sm whitespace-pre-wrap font-mono bg-muted/50 p-4 rounded">
                  {documentContent}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DocumentUploader;
