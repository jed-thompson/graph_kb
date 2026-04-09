import { useState, useEffect } from 'react';
import { FileText, Folder, X, Edit2, Check, Loader2 } from 'lucide-react';
import { MarkdownRenderer } from '@/components/chat/MarkdownRenderer';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { updateDocumentCategory, getDocument } from '@/lib/api/documents';

interface DocumentOverlayProps {
  document: {
    id: string;
    filename: string;
    category?: string | null;
    parent?: string | null;
    _chunkCount: number;
    content?: string | null;
  } | null;
  onClose: () => void;
  onCategoryUpdate?: (docId: string, newCategory: string) => void;
}

const PREDEFINED_CATEGORIES = ['Architecture', 'API', 'Requirements', 'Reference', 'Steering', 'Other'];

export function DocumentOverlay({ document, onClose, onCategoryUpdate }: DocumentOverlayProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editCategoryType, setEditCategoryType] = useState<string>('');
  const [customCategory, setCustomCategory] = useState<string>('');
  const [isSaving, setIsSaving] = useState(false);
  const [loadedContent, setLoadedContent] = useState<string | null | undefined>(undefined);
  const [isLoadingContent, setIsLoadingContent] = useState(false);

  useEffect(() => {
    if (!document) {
      setLoadedContent(undefined);
      return;
    }
    if (document.content && !document.filename.toLowerCase().endsWith('.pdf')) {
      setLoadedContent(document.content);
      return;
    }
    setIsLoadingContent(true);
    getDocument(document.id)
      .then(full => setLoadedContent(full.content ?? null))
      .catch(err => {
        console.error('Failed to fetch document content:', err);
        setLoadedContent(null);
      })
      .finally(() => setIsLoadingContent(false));
  }, [document?.id]);

  if (!document) return null;

  const startEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    const current = document.category || '';
    if (PREDEFINED_CATEGORIES.includes(current) || current === '') {
      setEditCategoryType(current);
      setCustomCategory('');
    } else {
      setEditCategoryType('Custom...');
      setCustomCategory(current);
    }
    setIsEditing(true);
  };

  const handleSaveCategory = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setIsSaving(true);
      const finalCategory = editCategoryType === 'Custom...' ? customCategory : editCategoryType;
      await updateDocumentCategory(document.id, finalCategory);
      if (onCategoryUpdate) {
        onCategoryUpdate(document.id, finalCategory);
      }
      setIsEditing(false);
    } catch (err) {
      console.error('Failed to update category:', err);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      {/* Backdrop - clickable to close */}
      <div
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Content - positioned on top of backdrop */}
      <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none">
        <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-[95vw] max-w-6xl max-h-[90vh] flex flex-col relative pointer-events-auto">
          {/* Overlay header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
            <div className="flex items-center gap-3">
              <FileText className="h-5 w-5 text-primary" />
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  {document.filename}
                </h2>
                <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                  {isEditing ? (
                    <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                      <Select value={editCategoryType} onValueChange={setEditCategoryType}>
                        <SelectTrigger className="w-[140px] h-8 text-sm">
                          <SelectValue placeholder="Category" />
                        </SelectTrigger>
                        <SelectContent side="bottom" position="popper" className="z-[100]">
                          {PREDEFINED_CATEGORIES.map(cat => (
                            <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                          ))}
                          <SelectItem value="Custom...">Custom...</SelectItem>
                        </SelectContent>
                      </Select>
                      {editCategoryType === 'Custom...' && (
                        <Input 
                          autoFocus
                          placeholder="Custom Category" 
                          value={customCategory}
                          onChange={(e) => setCustomCategory(e.target.value)}
                          className="w-[140px] h-8 text-sm"
                        />
                      )}
                      <Button variant="ghost" size="sm" className="h-8 px-2" onClick={handleSaveCategory} disabled={isSaving}>
                        <Check className="h-4 w-4 text-green-500" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-8 px-2" onClick={() => setIsEditing(false)}>
                        <X className="h-4 w-4 text-gray-500" />
                      </Button>
                    </div>
                  ) : (
                    <span className="flex items-center gap-1 group/cat">
                      <Folder className="h-3 w-3" />
                      {document.category || 'Uncategorized'}
                      <button 
                        onClick={startEditing} 
                        className="ml-1 opacity-0 group-hover/cat:opacity-100 transition-opacity hover:bg-gray-200 dark:hover:bg-gray-700 p-1 rounded-md"
                      >
                        <Edit2 className="h-3 w-3 text-gray-500" />
                      </button>
                    </span>
                  )}
                  {document.parent && (
                    <span>• {document.parent}</span>
                  )}
                  {document._chunkCount > 1 && (
                    <span>• {document._chunkCount} chunks</span>
                  )}
                </div>
              </div>
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
          {/* Overlay content */}
          <div className="flex-1 overflow-y-auto p-6">
            {isLoadingContent
              ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading content...</div>
              : loadedContent
                ? <MarkdownRenderer content={loadedContent} enableMermaid enableCodeHighlight />
                : <p className="text-sm text-muted-foreground">No content available</p>
            }
          </div>
        </div>
      </div>
    </>
  );
}
