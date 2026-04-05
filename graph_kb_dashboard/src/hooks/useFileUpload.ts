'use client';

import { useState, useRef, useCallback } from 'react';
import { apiClient } from '@/lib/api/client';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Allowed MIME types for document upload */
export const ALLOWED_MIME_TYPES = [
    'application/pdf',
    'text/markdown',
    'text/plain',
    'text/yaml',
    'application/x-yaml',
    'application/json',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
] as const;

/** File extensions for the accept attribute */
export const ACCEPTED_EXTENSIONS = '.pdf,.md,.markdown,.doc,.docx,.txt,.yaml,.yml,.json';

/** Default max file size (10MB) */
export const DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024;

/** File type extension regex */
const EXTENSION_REGEX = /\.(md|ya?ml|json|txt|pdf|docx?)$/i;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UploadedFile {
    id: string;
    filename: string;
    size?: number;
    mimeType?: string;
}

export interface UseFileUploadOptions {
    /** API endpoint for upload (default: '/docs/upload') */
    endpoint?: string;
    /** Maximum file size in bytes (default: 10MB) */
    maxFileSize?: number;
    /** Whether upload is disabled */
    disabled?: boolean;
    /** Whether hook should store uploaded files internally (default: true).
     * Set to false when using external state management (e.g., Zustand store). */
    storeInternally?: boolean;
    /** Callback when file uploads successfully */
    onUploadSuccess?: (file: UploadedFile) => void;
    /** Callback when upload fails */
    onUploadError?: (error: string) => void;
    /** Initial uploaded files (only used when storeInternally is true) */
    initialFiles?: UploadedFile[];
}

export interface UploadWithMetadataOptions {
    category?: string | null;
    parent?: string | null;
    indexForSearch?: boolean;
}

export interface UseFileUploadReturn {
    /** Currently uploaded files */
    uploadedFiles: UploadedFile[];
    /** Whether a file is currently uploading */
    isUploading: boolean;
    /** Whether user is dragging over drop zone */
    isDragging: boolean;
    /** Current error message */
    error: string;
    /** Ref for the hidden file input */
    fileInputRef: React.RefObject<HTMLInputElement>;
    /** Programmatically open file picker */
    openFilePicker: () => void;
    /** Handle file selection (from input or drop) */
    handleFileSelect: (file: File) => Promise<boolean>;
    /** Handle drag over event */
    handleDragOver: (e: React.DragEvent) => void;
    /** Handle drag leave event */
    handleDragLeave: (e: React.DragEvent) => void;
    /** Handle drop event */
    handleDrop: (e: React.DragEvent) => void;
    /** Handle input change event */
    handleInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    /** Remove an uploaded file by ID */
    removeFile: (id: string) => void;
    /** Clear all uploaded files */
    clearFiles: () => void;
    /** Clear error message */
    clearError: () => void;
    /** Validate a file without uploading */
    validateFile: (file: File) => string | null;
    /** Upload file with category/parent metadata */
    uploadWithMetadata: (file: File, metadata: UploadWithMetadataOptions) => Promise<UploadedFile | null>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Custom hook for file upload functionality.
 *
 * Provides standardized file type validation, drag-and-drop handling,
 * and upload state management.
 *
 * @example
 * ```tsx
 * const {
 *   uploadedFiles,
 *   isUploading,
 *   isDragging,
 *   error,
 *   fileInputRef,
 *   handleDragOver,
 *   handleDragLeave,
 *   handleDrop,
 *   handleInputChange,
 *   removeFile,
 * } = useFileUpload({
 *   onUploadSuccess: (file) => console.log('Uploaded:', file.filename),
 * });
 * ```
 */
export function useFileUpload(options: UseFileUploadOptions = {}): UseFileUploadReturn {
    const {
        endpoint = '/docs/upload',
        maxFileSize = DEFAULT_MAX_FILE_SIZE,
        disabled = false,
        onUploadSuccess,
        onUploadError,
        initialFiles = [],
    } = options;

    const fileInputRef = useRef<HTMLInputElement>(null);
    const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>(initialFiles);
    const [isUploading, setIsUploading] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const [error, setError] = useState('');

    /**
     * Validate file type and size.
     * Returns error message if invalid, null if valid.
     */
    const validateFile = useCallback((file: File): string | null => {
        const isValidType =
            ALLOWED_MIME_TYPES.includes(file.type as typeof ALLOWED_MIME_TYPES[number]) ||
            EXTENSION_REGEX.test(file.name);

        if (!isValidType) {
            return 'Invalid file type. Please upload PDF, Markdown, Word, YAML, JSON, or TXT documents.';
        }

        if (file.size > maxFileSize) {
            const maxMB = (maxFileSize / (1024 * 1024)).toFixed(0);
            return `File too large. Maximum size is ${maxMB}MB.`;
        }

        return null;
    }, [maxFileSize]);

    /**
     * Handle file selection and upload.
     * Returns true if upload succeeded, false otherwise.
     */
    const handleFileSelect = useCallback(async (file: File): Promise<boolean> => {
        if (disabled) return false;

        const validationError = validateFile(file);
        if (validationError) {
            setError(validationError);
            onUploadError?.(validationError);
            return false;
        }

        setIsUploading(true);
        setError('');

        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await apiClient.postForm<{ id: string; filename: string; size?: number; mime_type?: string }>(
                endpoint,
                formData,
            );

            const uploadedFile: UploadedFile = {
                id: response.id,
                filename: response.filename,
                size: response.size,
                mimeType: response.mime_type,
            };

            setUploadedFiles(prev => [...prev, uploadedFile]);
            onUploadSuccess?.(uploadedFile);
            return true;
        } catch (err) {
            const message = 'Failed to upload document. Please try again.';
            console.error('Upload failed:', err);
            setError(message);
            onUploadError?.(message);
            return false;
        } finally {
            setIsUploading(false);
        }
    }, [disabled, endpoint, onUploadError, onUploadSuccess, validateFile]);

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        if (!disabled) {
            setIsDragging(true);
        }
    }, [disabled]);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        if (disabled) return;

        const file = e.dataTransfer.files?.[0];
        if (file) {
            handleFileSelect(file);
        }
    }, [disabled, handleFileSelect]);

    const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            handleFileSelect(file);
        }
        // Reset input so same file can be selected again
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    }, [handleFileSelect]);

    const openFilePicker = useCallback(() => {
        fileInputRef.current?.click();
    }, []);

    const removeFile = useCallback((id: string) => {
        setUploadedFiles(prev => prev.filter(f => f.id !== id));
    }, []);

    const clearFiles = useCallback(() => {
        setUploadedFiles([]);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    }, []);

    const clearError = useCallback(() => {
        setError('');
    }, []);

    /**
     * Upload file with category/parent metadata.
     * Returns the uploaded file or null on failure.
     */
    const uploadWithMetadata = useCallback(async (
        file: File,
        metadata: UploadWithMetadataOptions
    ): Promise<UploadedFile | null> => {
        if (disabled) return null;

        const validationError = validateFile(file);
        if (validationError) {
            setError(validationError);
            onUploadError?.(validationError);
            return null;
        }

        setIsUploading(true);
        setError('');

        try {
            const formData = new FormData();
            formData.append('file', file);
            if (metadata.category) {
                formData.append('category', metadata.category);
            }
            if (metadata.parent) {
                formData.append('parent', metadata.parent);
            }
            formData.append('index_for_search', String(metadata.indexForSearch ?? true));

            const response = await apiClient.postForm<{
                id: string;
                filename: string;
                size?: number;
                mime_type?: string;
                category?: string | null;
                parent?: string | null;
            }>(
                endpoint,
                formData,
            );

            const uploadedFile: UploadedFile = {
                id: response.id,
                filename: response.filename,
                size: response.size,
                mimeType: response.mime_type,
            };

            setUploadedFiles(prev => [...prev, uploadedFile]);
            onUploadSuccess?.(uploadedFile);
            return uploadedFile;
        } catch (err) {
            const message = 'Failed to upload document. Please try again.';
            console.error('Upload failed:', err);
            setError(message);
            onUploadError?.(message);
            return null;
        } finally {
            setIsUploading(false);
        }
    }, [disabled, endpoint, onUploadError, onUploadSuccess, validateFile]);

    return {
        uploadedFiles,
        isUploading,
        isDragging,
        error,
        fileInputRef,
        openFilePicker,
        handleFileSelect,
        handleDragOver,
        handleDragLeave,
        handleDrop,
        handleInputChange,
        removeFile,
        clearFiles,
        clearError,
        validateFile,
        uploadWithMetadata,
    };
}

export default useFileUpload;
