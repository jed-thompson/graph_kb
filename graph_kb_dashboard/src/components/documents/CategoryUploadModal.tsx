'use client';

import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tag, PlusCircle, Folder, Upload } from 'lucide-react';

/** Simple file-like object for display purposes */
interface FileLike {
  name: string;
}

 interface CategoryUploadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  files: Array<File | FileLike>;
  existingCategories: string[];
  existingParents: string[];
  onUpload: (options: {
    category: string | null;
    parent: string | null;
    indexForSearch: boolean;
  }) => void;
  onCancel: () => void;
  /** Current values for editing existing document */
  initialCategory?: string;
  initialParent?: string;
  initialIndexForSearch?: boolean;
}

export function CategoryUploadModal({
  open,
  onOpenChange,
  files,
  existingCategories,
  existingParents,
  onUpload,
  onCancel,
}: CategoryUploadModalProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [customCategory, setCustomCategory] = useState<string>('');
  const [selectedParent, setSelectedParent] = useState<string>('');
  const [customParent, setCustomParent] = useState<string>('');
  const [indexForSearch, setIndexForSearch] = useState(true);

  // Determine the final category value
  const finalCategory = selectedCategory === '__custom__' ? customCategory.trim() : selectedCategory || null;
  const finalParent = selectedParent === '__custom__' ? customParent.trim() : selectedParent || null;

  const handleUpload = () => {
    onUpload({
      category: finalCategory,
      parent: finalParent,
      indexForSearch,
    });
    // Reset form
    setSelectedCategory('');
    setCustomCategory('');
    setSelectedParent('');
    setCustomParent('');
    setIndexForSearch(true);
  };

  const fileCount = files.length;
  const fileNames = files.map(f => f.name).join(', ');
  const displayNames = fileCount === 1
    ? fileNames
    : `${fileCount} files selected`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Tag className="h-5 w-5 text-primary" />
            Categorize Documents
          </DialogTitle>
          <DialogDescription>
            Select a category and optional parent for: <span className="font-medium">{displayNames}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Category Selection */}
          <div className="space-y-3">
            <label className="text-sm font-medium text-foreground">Category</label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { value: '', label: 'No category' },
                { value: 'specification', label: 'Specification' },
                { value: 'requirements', label: 'Requirements' },
                { value: 'design', label: 'Design' },
                { value: 'api-docs', label: 'API Docs' },
                { value: 'technical', label: 'Technical' },
                { value: 'reference', label: 'Reference' },
                { value: '__custom__', label: 'Custom...' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSelectedCategory(opt.value)}
                  className={`px-3 py-2 text-sm rounded-md border transition-colors ${
                    selectedCategory === opt.value
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:border-primary/50'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {selectedCategory === '__custom__' && (
              <Input
                placeholder="Enter custom category..."
                value={customCategory}
                onChange={(e) => setCustomCategory(e.target.value)}
                className="mt-2"
              />
            )}
          </div>

          {/* Parent Selection */}
          <div className="space-y-3">
            <label className="text-sm font-medium text-foreground flex items-center gap-2">
              <Folder className="h-4 w-4" />
              Parent (Optional)
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setSelectedParent('')}
                className={`px-3 py-2 text-sm rounded-md border transition-colors ${
                  selectedParent === ''
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:border-primary/50'
                }`}
              >
                No parent
              </button>
              {existingParents.slice(0, 10).map((parent) => (
                <button
                  key={parent}
                  onClick={() => setSelectedParent(parent)}
                  className={`px-3 py-2 text-sm rounded-md border transition-colors ${
                    selectedParent === parent
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:border-primary/50'
                  }`}
                >
                  {parent}
                </button>
              ))}
              <button
                onClick={() => setSelectedParent('__custom__')}
                className={`px-3 py-2 text-sm rounded-md border transition-colors flex items-center gap-1 ${
                  selectedParent === '__custom__'
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:border-primary/50'
                }`}
              >
                <PlusCircle className="h-3 w-3" />
                Custom
              </button>
            </div>
            {selectedParent === '__custom__' && (
              <Input
                placeholder="Enter parent name..."
                value={customParent}
                onChange={(e) => setCustomParent(e.target.value)}
                className="mt-2"
              />
            )}
          </div>

          {/* Index for Search Toggle */}
          <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
            <div className="space-y-0.5">
              <div className="text-sm font-medium">Index for Search</div>
              <div className="text-xs text-muted-foreground">
                Enable semantic search for this document
              </div>
            </div>
            <Switch
              checked={indexForSearch}
              onCheckedChange={setIndexForSearch}
            />
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={handleUpload} disabled={selectedCategory === '__custom__' && !customCategory.trim()}>
            <Upload className="h-4 w-4 mr-2" />
            Upload {fileCount} File{fileCount > 1 ? 's' : ''}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default CategoryUploadModal;
