'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  FileText,
  Search,
  Upload,
  Folder,
  Trash2,
  Eye,
  RefreshCw,
  X,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  Filter,
  CheckCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { AlertCard } from '@/components/ui/alert-card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { listDocuments, uploadDocument, deleteDocument, getFilterOptions } from '@/lib/api/documents';
import type { DocumentResponse, DocumentFilterOptions } from '@/lib/types/api';
import { DocumentOverlay } from '@/components/documents/DocumentOverlay';

interface SkippedFile {
  file: File;
  parent?: string;
  category?: string;
}

interface PendingFile {
  id: string;
  file: File;
  category: string;
  customCategory: string;
}

interface AggregatedDocument extends DocumentResponse {
  _chunkCount: number;
  _chunks: DocumentResponse[];
  _aggregatedId: string;
}

interface GroupedDocumentsRaw {
  [key: string]: {
    label: string;
    type: 'parent' | 'category' | 'uncategorized';
    documents: DocumentResponse[];
  };
}

interface GroupedDocuments {
  [key: string]: {
    label: string;
    type: 'parent' | 'category' | 'uncategorized';
    documents: AggregatedDocument[];
  };
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<AggregatedDocument | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [skippedFiles, setSkippedFiles] = useState<SkippedFile[]>([]);
  const [forceUploading, setForceUploading] = useState<string | null>(null);
  const [filterOptions, setFilterOptions] = useState<DocumentFilterOptions>({ parents: [], categories: [] });
  const [selectedParent, setSelectedParent] = useState<string>('__all__');
  const [selectedCategory, setSelectedCategory] = useState<string>('__all__');
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'tree' | 'list'>('tree');
  const [indexForSearch, setIndexForSearch] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [pendingUploads, setPendingUploads] = useState<PendingFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const PREDEFINED_CATEGORIES = ['Architecture', 'API', 'Requirements', 'Reference', 'Steering', 'Other'];

  const fetchFilterOptions = useCallback(async () => {
    try {
      const options = await getFilterOptions();
      setFilterOptions(options);
    } catch (err) {
      console.error('Failed to load filter options:', err);
    }
  }, []);

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params: { parent?: string; category?: string } = {};
      if (selectedParent && selectedParent !== '__all__') params.parent = selectedParent;
      if (selectedCategory && selectedCategory !== '__all__') params.category = selectedCategory;

      const data = await listDocuments(Object.keys(params).length > 0 ? params : undefined);
      setDocuments(data.documents);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load documents';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [selectedParent, selectedCategory]);

  useEffect(() => {
    fetchFilterOptions();
  }, [fetchFilterOptions]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Auto-expand groups when documents are first loaded
  useEffect(() => {
    if (documents.length > 0 && expandedGroups.size === 0) {
      const groupKeys = new Set<string>();
      documents.forEach((doc) => {
        if (doc.parent) groupKeys.add(doc.parent);
        else if (doc.category) groupKeys.add(`cat:${doc.category}`);
        else groupKeys.add('__uncategorized__');
      });
      setExpandedGroups(groupKeys);
    }
  }, [documents]);

  // Group documents by parent; when no parent, fall back to category
  const groupedDocuments = useMemo((): GroupedDocumentsRaw => {
    const groups: GroupedDocumentsRaw = {};

    documents.forEach((doc) => {
      let groupKey: string;
      let groupLabel: string;
      let groupType: 'parent' | 'category' | 'uncategorized';

      if (doc.parent) {
        groupKey = doc.parent;
        groupLabel = doc.parent;
        groupType = 'parent';
      } else if (doc.category) {
        groupKey = `cat:${doc.category}`;
        groupLabel = doc.category;
        groupType = 'category';
      } else {
        groupKey = '__uncategorized__';
        groupLabel = 'Uncategorized';
        groupType = 'uncategorized';
      }

      if (!groups[groupKey]) {
        groups[groupKey] = {
          label: groupLabel,
          type: groupType,
          documents: [],
        };
      }
      groups[groupKey].documents.push(doc);
    });

    // Sort groups alphabetically, but put uncategorized last
    return Object.fromEntries(
      Object.entries(groups).sort(([keyA], [keyB]) => {
        if (keyA === '__uncategorized__') return 1;
        if (keyB === '__uncategorized__') return -1;
        return keyA.localeCompare(keyB);
      })
    );
  }, [documents]);

  // Filter documents based on search query
  const filteredGroups = useMemo(() => {
    if (!searchQuery) return groupedDocuments;

    const filtered: GroupedDocumentsRaw = {};
    const q = searchQuery.toLowerCase();

    Object.entries(groupedDocuments).forEach(([key, group]) => {
      const matchingDocs = group.documents.filter(
        (doc) =>
          doc.filename.toLowerCase().includes(q) ||
          (doc.category?.toLowerCase().includes(q) ?? false)
      );

      if (matchingDocs.length > 0 || group.label.toLowerCase().includes(q)) {
        filtered[key] = {
          ...group,
          documents: matchingDocs.length > 0 ? matchingDocs : group.documents,
        };
      }
    });

    return filtered;
  }, [groupedDocuments, searchQuery]);

  // Aggregate documents by filename within each group
  const aggregatedGroups = useMemo(() => {
    const aggregated: GroupedDocuments = {};

    Object.entries(filteredGroups).forEach(([key, group]) => {
      const byFilename: { [filename: string]: DocumentResponse[] } = {};

      group.documents.forEach((doc) => {
        const filename = doc.filename;
        if (!byFilename[filename]) {
          byFilename[filename] = [];
        }
        byFilename[filename].push(doc);
      });

      // Create aggregated documents with chunk count
      const aggregatedDocs: (DocumentResponse & { _chunkCount: number; _chunks: DocumentResponse[]; _aggregatedId: string })[] =
        Object.entries(byFilename).map(([filename, chunks]) => {
          // Use the first chunk as the representative
          const first = chunks[0];
          // Concatenate all chunk content for viewing
          const allContent = chunks.map(c => c.content || '').join('\n\n---\n\n');
          return {
            ...first,
            id: first.id, // Keep original ID for first chunk
            filename,
            content: allContent, // Combined content from all chunks
            _chunkCount: chunks.length,
            _chunks: chunks,
            _aggregatedId: `agg-${filename}-${key}`, // Unique ID for React key
          };
        });

      aggregated[key] = {
        ...group,
        documents: aggregatedDocs,
      };
    });

    return aggregated;
  }, [filteredGroups]);

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const expandAll = () => {
    setExpandedGroups(new Set(Object.keys(aggregatedGroups)));
  };

  const collapseAll = () => {
    setExpandedGroups(new Set());
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const newPending: PendingFile[] = Array.from(files).map((file) => ({
      id: Math.random().toString(36).substring(7),
      file,
      category: 'Reference',
      customCategory: '',
    }));
    setPendingUploads((prev) => [...prev, ...newPending]);

    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const confirmUploads = async () => {
    if (pendingUploads.length === 0) return;

    setIsUploading(true);
    setSkippedFiles([]);
    setUploadStatus(null);
    const newSkipped: SkippedFile[] = [];
    let successCount = 0;
    let errorCount = 0;

    try {
      for (const pending of pendingUploads) {
        const finalCategory = pending.category === 'Custom...' ? pending.customCategory : pending.category;
        try {
          await uploadDocument(pending.file, undefined, finalCategory, undefined, indexForSearch);
          successCount++;
        } catch (err: unknown) {
          const isSkipped =
            err instanceof Error &&
            (err.message.includes('already exists') || err.message.includes('skipped'));
          const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
          const isConflict = axiosErr?.response?.status === 409;
          const detailSkipped = axiosErr?.response?.data?.detail?.includes('already exists');

          if (isSkipped || isConflict || detailSkipped) {
            newSkipped.push({ file: pending.file, category: finalCategory });
          } else {
            console.error(`Failed to upload ${pending.file.name}:`, err);
            errorCount++;
          }
        }
      }

      if (newSkipped.length > 0) {
        setSkippedFiles(newSkipped);
      }

      // Show success/error status
      if (successCount > 0 && errorCount === 0) {
        setUploadStatus({ type: 'success', message: `Successfully uploaded ${successCount} document${successCount > 1 ? 's' : ''}` });
      } else if (errorCount > 0) {
        setUploadStatus({ type: 'error', message: `Uploaded ${successCount} document${successCount !== 1 ? 's' : ''}, ${errorCount} failed` });
      }

      await Promise.all([fetchDocuments(), fetchFilterOptions()]);
      setPendingUploads([]); // Clear staging area
    } finally {
      setIsUploading(false);
    }
  };

  const cancelUploads = () => {
    setPendingUploads([]);
  };

  const updatePendingCategory = (id: string, field: 'category' | 'customCategory', value: string) => {
    setPendingUploads(prev => prev.map(p => p.id === id ? { ...p, [field]: value } : p));
  };

  const removePendingFile = (id: string) => {
    setPendingUploads(prev => prev.filter(p => p.id !== id));
  };

  const handleForceUpdate = async (skipped: SkippedFile) => {
    setForceUploading(skipped.file.name);
    try {
      await uploadDocument(skipped.file, skipped.parent, skipped.category, true, indexForSearch);
      setSkippedFiles((prev) => prev.filter((s) => s.file.name !== skipped.file.name));
      await Promise.all([fetchDocuments(), fetchFilterOptions()]);
    } catch (err) {
      console.error(`Force update failed for ${skipped.file.name}:`, err);
    } finally {
      setForceUploading(null);
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      if (selectedDoc?.id === docId) setSelectedDoc(null);
      await fetchFilterOptions();
    } catch (err) {
      console.error('Failed to delete document:', err);
    }
  };

  const clearFilters = () => {
    setSelectedParent('__all__');
    setSelectedCategory('__all__');
    setSearchQuery('');
  };

  const hasActiveFilters = (selectedParent && selectedParent !== '__all__') || (selectedCategory && selectedCategory !== '__all__') || searchQuery;

  // Count unique documents (by filename)
  const uniqueDocCount = useMemo(() => {
    const filenames = new Set(documents.map((d) => d.filename));
    return filenames.size;
  }, [documents]);

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Documents</h1>
          <p className="text-muted-foreground">
            Manage documents stored in S3/MinIO blob storage
            {documents.length > 0 && (
              <span className="ml-2">
                ({uniqueDocCount} unique documents, {documents.length} total chunks)
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={fetchDocuments} disabled={isLoading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
            <Upload className="h-4 w-4 mr-2" />
            Stage Documents
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />
        </div>
      </div>

      {/* Staging Area */}
      {pendingUploads.length > 0 && (
        <Card className="border-blue-300 bg-blue-50/50 dark:bg-blue-900/10">
          <CardContent className="py-4 space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-lg">Staged for Upload</h3>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={cancelUploads}>Cancel</Button>
                <Button size="sm" onClick={confirmUploads} disabled={isUploading}>
                  {isUploading ? 'Uploading...' : `Confirm Upload (${pendingUploads.length})`}
                </Button>
              </div>
            </div>
            <div className="space-y-3">
              {pendingUploads.map((pending) => (
                <div key={pending.id} className="flex flex-col sm:flex-row sm:items-center gap-3 bg-white dark:bg-gray-800 p-3 rounded-md shadow-sm border">
                  <div className="flex items-center gap-2 flex-1 overflow-hidden">
                    <FileText className="h-4 w-4 text-blue-500 shrink-0" />
                    <span className="truncate text-sm font-medium">{pending.file.name}</span>
                  </div>
                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <Select value={pending.category} onValueChange={(val) => updatePendingCategory(pending.id, 'category', val)}>
                      <SelectTrigger className="w-[140px] h-8 text-sm">
                        <SelectValue placeholder="Category" />
                      </SelectTrigger>
                      <SelectContent>
                        {PREDEFINED_CATEGORIES.map(cat => (
                          <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                        ))}
                        <SelectItem value="Custom...">Custom...</SelectItem>
                      </SelectContent>
                    </Select>
                    {pending.category === 'Custom...' && (
                      <Input 
                        placeholder="Custom Category" 
                        value={pending.customCategory}
                        onChange={(e) => updatePendingCategory(pending.id, 'customCategory', e.target.value)}
                        className="w-[140px] h-8 text-sm"
                      />
                    )}
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-red-500" onClick={() => removePendingFile(pending.id)}>
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Upload status banner */}
      {uploadStatus && (
        <Card className={uploadStatus.type === 'success' ? 'border-green-300 bg-green-50 dark:bg-green-900/10' : 'border-red-300 bg-red-50 dark:bg-red-900/10'}>
          <CardContent className="py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {uploadStatus.type === 'success' ? (
                  <CheckCircle className="h-5 w-5 text-green-600" />
                ) : (
                  <AlertTriangle className="h-5 w-5 text-red-600" />
                )}
                <p className={uploadStatus.type === 'success' ? 'text-green-800 dark:text-green-200' : 'text-red-800 dark:text-red-200'}>
                  {uploadStatus.message}
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setUploadStatus(null)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Skipped files banner */}
      {skippedFiles.length > 0 && (
        <Card className="border-yellow-300 bg-yellow-50 dark:bg-yellow-900/10">
          <CardContent className="py-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5 shrink-0" />
              <div className="flex-1 space-y-2">
                <p className="font-medium text-yellow-800 dark:text-yellow-200">
                  {skippedFiles.length} file(s) skipped — already exist
                </p>
                {skippedFiles.map((s) => (
                  <div key={s.file.name} className="flex items-center gap-2">
                    <span className="text-sm">{s.file.name}</span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={forceUploading === s.file.name}
                      onClick={() => handleForceUpdate(s)}
                    >
                      {forceUploading === s.file.name ? 'Updating...' : 'Force Update'}
                    </Button>
                  </div>
                ))}
                <Button size="sm" variant="ghost" onClick={() => setSkippedFiles([])}>
                  <X className="h-3 w-3 mr-1" /> Dismiss
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="space-y-4">
        <div className="flex flex-wrap gap-4 items-center">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search documents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>

          {/* Parent/Repository filter */}
          <Select value={selectedParent} onValueChange={setSelectedParent}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="All Repositories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All Repositories</SelectItem>
              {filterOptions.parents.map((parent) => (
                <SelectItem key={parent} value={parent}>
                  {parent}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Category filter */}
          <Select value={selectedCategory} onValueChange={setSelectedCategory}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All Categories</SelectItem>
              {filterOptions.categories.map((category) => (
                <SelectItem key={category} value={category}>
                  {category}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Clear filters */}
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="h-4 w-4 mr-1" />
              Clear Filters
            </Button>
          )}
        </div>

        {/* Active filters display */}
        {hasActiveFilters && (
          <div className="flex flex-wrap gap-2">
            {selectedParent && selectedParent !== '__all__' && (
              <Badge variant="secondary" className="gap-1">
                <Filter className="h-3 w-3" />
                Repo: {selectedParent}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => setSelectedParent('__all__')}
                />
              </Badge>
            )}
            {selectedCategory && selectedCategory !== '__all__' && (
              <Badge variant="secondary" className="gap-1">
                <Filter className="h-3 w-3" />
                Category: {selectedCategory}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => setSelectedCategory('__all__')}
                />
              </Badge>
            )}
            {searchQuery && (
              <Badge variant="secondary" className="gap-1">
                <Search className="h-3 w-3" />
                Search: {searchQuery}
                <X className="h-3 w-3 cursor-pointer" onClick={() => setSearchQuery('')} />
              </Badge>
            )}
          </div>
        )}
      </div>

      {/* View controls */}
      <div className="flex gap-2 items-center">
        <Button variant="outline" size="sm" onClick={expandAll}>
          Expand All
        </Button>
        <Button variant="outline" size="sm" onClick={collapseAll}>
          Collapse All
        </Button>
      </div>

      {/* Document tree/list */}
      <div className="grid gap-2">
        {error ? (
          <AlertCard
            variant="error"
            title="Error loading documents"
            description={error}
            onRetry={fetchDocuments}
            centered
          />
        ) : isLoading ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              Loading documents...
            </CardContent>
          </Card>
        ) : Object.keys(aggregatedGroups).length === 0 ? (
          <EmptyState
            icon={Folder}
            title="No documents found"
            description="Upload documents to get started"
          />
        ) : (
          Object.entries(aggregatedGroups).map(([groupKey, group]) => (
            <div key={groupKey} className="border rounded-lg">
              {/* Group header */}
              <div
                className="flex items-center gap-2 p-3 bg-muted/50 cursor-pointer hover:bg-muted/70"
                onClick={() => toggleGroup(groupKey)}
              >
                {expandedGroups.has(groupKey) ? (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                )}
                <Folder className="h-5 w-5 text-blue-500" />
                <span className="font-medium">{group.label}</span>
                <Badge variant="outline" className="ml-auto">
                  {group.documents.length} document{group.documents.length !== 1 ? 's' : ''}
                </Badge>
              </div>

              {/* Group documents */}
              {expandedGroups.has(groupKey) && (
                <div className="border-t">
                  {group.documents.map((doc) => {
                    const chunkCount = doc._chunkCount || 1;
                    const chunks = doc._chunks || [doc];
                    const aggId = doc._aggregatedId || doc.id;

                    return (
                      <div
                        key={aggId}
                        className={`flex items-center justify-between p-3 border-b last:border-b-0 hover:bg-muted/30 cursor-pointer ${selectedDoc?._aggregatedId === aggId ? 'bg-primary/10' : ''
                          }`}
                        onClick={() => setSelectedDoc(doc)}
                      >
                        <div className="flex items-center gap-3">
                          <FileText className="h-4 w-4 text-muted-foreground" />
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{doc.filename}</span>
                              {chunkCount > 1 && (
                                <Badge variant="secondary" className="text-xs">
                                  {chunkCount} chunks
                                </Badge>
                              )}
                            </div>
                            <div className="flex gap-2 text-xs text-muted-foreground">
                              {doc.category && <span>Category: {doc.category}</span>}
                              {doc.created_at && (
                                <span>{new Date(doc.created_at).toLocaleDateString()}</span>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedDoc(selectedDoc?._aggregatedId === aggId ? null : doc);
                            }}
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-red-500 hover:text-red-700"
                            onClick={(e) => {
                              e.stopPropagation();
                              // Delete all chunks for this document
                              chunks.forEach((c) => handleDelete(c.id));
                              if (selectedDoc?._aggregatedId === aggId) setSelectedDoc(null);
                            }}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <DocumentOverlay 
        document={selectedDoc} 
        onClose={() => setSelectedDoc(null)} 
        onCategoryUpdate={(docId, newCat) => {
          setSelectedDoc(prev => prev ? { ...prev, category: newCat } : null);
          fetchDocuments(); // refresh list
        }}
      />
    </div>
  );
}
