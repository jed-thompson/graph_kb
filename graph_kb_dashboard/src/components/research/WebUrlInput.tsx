'use client';

import { useState, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { X, Globe, Plus } from 'lucide-react';
import { useResearchStore } from '@/lib/store/researchStore';

interface WebUrlInputProps {
  disabled?: boolean;
}

/**
 * WebUrlInput - URL submission component with chip list display.
 * Allows adding multiple web URLs for research context gathering.
 */
export function WebUrlInput({ disabled = false }: WebUrlInputProps) {
  const [inputValue, setInputValue] = useState('');
  const [error, setError] = useState('');

  const { webUrls, addWebUrl, removeWebUrl } = useResearchStore();

  const validateUrl = useCallback((url: string): boolean => {
    try {
      const parsed = new URL(url);
      return ['http:', 'https:'].includes(parsed.protocol);
    } catch {
      return false;
    }
  }, []);

  const handleAddUrl = useCallback(() => {
    const trimmed = inputValue.trim();

    if (!trimmed) {
      setError('Please enter a URL');
      return;
    }

    // Add protocol if missing
    const urlWithProtocol = trimmed.startsWith('http') ? trimmed : `https://${trimmed}`;

    if (!validateUrl(urlWithProtocol)) {
      setError('Please enter a valid URL');
      return;
    }

    if (webUrls.includes(urlWithProtocol)) {
      setError('URL already added');
      return;
    }

    addWebUrl(urlWithProtocol);
    setInputValue('');
    setError('');
  }, [inputValue, webUrls, addWebUrl, validateUrl]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleAddUrl();
      }
    },
    [handleAddUrl]
  );

  return (
    <div className="space-y-3">
      <Label className="flex items-center gap-2">
        <Globe className="h-4 w-4" />
        Web URLs for Context
      </Label>

      <div className="flex gap-2">
        <Input
          placeholder="https://example.com/docs"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            setError('');
          }}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          className="flex-1"
        />
        <Button
          variant="outline"
          size="icon"
          onClick={handleAddUrl}
          disabled={disabled || !inputValue.trim()}
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {/* URL List - Vertical */}
      {webUrls.length > 0 && (
        <div className="space-y-2 mt-3">
          {webUrls.map((url) => (
            <div
              key={url}
              className="flex items-center gap-2 px-3 py-2 bg-muted/50 border rounded-lg text-sm group"
            >
              <Globe className="h-4 w-4 text-primary shrink-0" />
              <span className="flex-1 truncate text-muted-foreground" title={url}>
                {url}
              </span>
              <button
                onClick={() => removeWebUrl(url)}
                disabled={disabled}
                className="opacity-50 group-hover:opacity-100 hover:bg-destructive/20 rounded p-1 disabled:opacity-30 transition-opacity"
                title="Remove URL"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {webUrls.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Add web URLs to fetch additional context during research
        </p>
      )}
    </div>
  );
}

export default WebUrlInput;
