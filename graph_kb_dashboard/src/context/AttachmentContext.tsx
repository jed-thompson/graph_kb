'use client';

import {
    createContext,
    useContext,
    useCallback,
    useState,
    ReactNode,
} from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AttachedFile {
    id: string;
    name: string;
    content: string;
    mimeType: string;
    addedAt: Date;
}

export interface AttachmentContextValue {
    files: AttachedFile[];
    addFile: (file: File) => void;
    removeFile: (fileId: string) => void;
    clearAll: () => void;
    getContextFiles: () => AttachedFile[];
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AttachmentContext = createContext<AttachmentContextValue | null>(null);

export function useAttachments(): AttachmentContextValue {
    const ctx = useContext(AttachmentContext);
    if (!ctx) {
        throw new Error('useAttachments must be used within an AttachmentProvider');
    }
    return ctx;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AttachmentProvider({ children }: { children: ReactNode }) {
    const [files, setFiles] = useState<AttachedFile[]>([]);

    const addFile = useCallback((file: File) => {
        const reader = new FileReader();
        reader.onload = () => {
            const content = reader.result as string;
            const attached: AttachedFile = {
                id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
                name: file.name,
                content,
                mimeType: file.type || 'application/octet-stream',
                addedAt: new Date(),
            };
            setFiles((prev) => [...prev, attached]);
        };
        reader.readAsText(file);
    }, []);

    const removeFile = useCallback((fileId: string) => {
        setFiles((prev) => prev.filter((f) => f.id !== fileId));
    }, []);

    const clearAll = useCallback(() => {
        setFiles([]);
    }, []);

    const getContextFiles = useCallback((): AttachedFile[] => {
        return files;
    }, [files]);

    const value: AttachmentContextValue = {
        files,
        addFile,
        removeFile,
        clearAll,
        getContextFiles,
    };

    return (
        <AttachmentContext.Provider value={value}>
            {children}
        </AttachmentContext.Provider>
    );
}
