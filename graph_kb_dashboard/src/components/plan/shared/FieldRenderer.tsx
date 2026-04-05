'use client';

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { PhaseField } from '@shared/websocket-events';
import { FileUploadField } from './FileUploadField';
import { DocumentListField } from './DocumentListField';
import { fuzzyMatch } from '@/lib/utils/fuzzyMatch';

export interface FieldRendererProps {
    field: PhaseField;
    value: unknown;
    error?: string;
    onChange: (value: unknown) => void;
    /** Plan session ID — forwarded to FileUploadField for plan-scoped uploads. */
    sessionId?: string | null;
}

function resolveOption(opt: string | { label: string; value: string }): { label: string; value: string } {
    return typeof opt === 'string' ? { label: opt, value: opt } : opt;
}

export function FieldRenderer({ field, value, error, onChange, sessionId }: FieldRendererProps) {
    switch (field.type) {
        case 'text':
            return (
                <div className="space-y-2">
                    <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
                    <Input
                        value={(value as string) || ''}
                        onChange={(e) => onChange(e.target.value)}
                        placeholder={field.placeholder}
                        className={error ? 'border-red-500' : ''}
                    />
                    {error && <p className="text-sm text-red-500">{error}</p>}
                </div>
            );

        case 'textarea':
            return (
                <div className="space-y-2">
                    <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
                    <Textarea
                        value={(value as string) || ''}
                        onChange={(e) => onChange(e.target.value)}
                        placeholder={field.placeholder}
                        rows={5}
                        className={error ? 'border-red-500' : ''}
                    />
                    {error && <p className="text-sm text-red-500">{error}</p>}
                </div>
            );

        case 'select':
            return (
                <div className="space-y-2">
                    <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
                    <select
                        value={(value as string) || ''}
                        onChange={(e) => onChange(e.target.value)}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                        <option value="">{field.placeholder || 'Select...'}</option>
                        {field.options?.map(opt => {
                            const { label, value: optVal } = resolveOption(opt);
                            return (
                                <option key={optVal} value={optVal}>{label}</option>
                            );
                        })}
                    </select>
                    {error && <p className="text-sm text-red-500">{error}</p>}
                </div>
            );

        case 'searchable_select':
            return <SearchableSelectField field={field} value={value} error={error} onChange={onChange} />;

        case 'multiselect':
            return (
                <div className="space-y-2">
                    <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
                    <div className="flex flex-wrap gap-2">
                        {field.options?.map(opt => {
                            const { label, value: optVal } = resolveOption(opt);
                            const selected = Array.isArray(value) && value.includes(optVal);
                            return (
                                <button
                                    key={optVal}
                                    type="button"
                                    onClick={() => {
                                        const current = Array.isArray(value) ? value : [];
                                        onChange(selected ? current.filter((v: string) => v !== optVal) : [...current, optVal]);
                                    }}
                                    className={`px-3 py-1.5 rounded-md border text-sm transition-colors ${selected
                                        ? 'border-primary bg-primary/10 text-primary'
                                        : 'border-border hover:border-primary/50'
                                        }`}
                                >
                                    {label}
                                </button>
                            );
                        })}
                    </div>
                    {error && <p className="text-sm text-red-500">{error}</p>}
                </div>
            );

        case 'url_list':
            return <UrlListField field={field} value={value} error={error} onChange={onChange} />;

        case 'file':
            return <FileUploadField field={field} value={value} error={error} onChange={onChange} sessionId={sessionId} />;

        case 'document_list':
            return <DocumentListField field={field} value={value} error={error} onChange={onChange} sessionId={sessionId} />;

        case 'json':
            return (
                <div className="space-y-2">
                    <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
                    <Textarea
                        value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                        onChange={(e) => onChange(e.target.value)}
                        placeholder={field.placeholder || '{ }'}
                        rows={6}
                        className={`font-mono text-sm ${error ? 'border-red-500' : ''}`}
                    />
                    {error && <p className="text-sm text-red-500">{error}</p>}
                </div>
            );

        default:
            return null;
    }
}

function SearchableSelectField({ field, value, error, onChange }: FieldRendererProps) {
    const resolvedOptions = useMemo(
        () => (field.options || []).map(resolveOption),
        [field.options]
    );
    const [search, setSearch] = useState('');
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const currentLabel = useMemo(() => {
        const found = resolvedOptions.find(o => o.value === (value as string));
        return found?.label ?? '';
    }, [resolvedOptions, value]);

    const filtered = useMemo(() => {
        if (!search) return resolvedOptions;
        return resolvedOptions.filter(o => fuzzyMatch(search, o.label));
    }, [search, resolvedOptions]);

    const handleSelect = useCallback((optVal: string) => {
        onChange(optVal);
        setIsOpen(false);
        setSearch('');
    }, [onChange]);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    return (
        <div className="space-y-2" ref={containerRef}>
            <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
            <div className="relative">
                <Input
                    value={search || (isOpen ? '' : currentLabel)}
                    onChange={(e) => {
                        setSearch(e.target.value);
                        setIsOpen(true);
                    }}
                    onFocus={() => setIsOpen(true)}
                    placeholder={field.placeholder || 'Search...'}
                    className={error ? 'border-red-500' : ''}
                />
                {isOpen && filtered.length > 0 && (
                    <ul className="absolute z-50 mt-1 max-h-48 w-full overflow-auto rounded-md border border-input bg-popover text-sm shadow-md">
                        {filtered.map(opt => (
                            <li
                                key={opt.value}
                                className={`cursor-pointer px-3 py-2 transition-colors hover:bg-muted ${
                                    opt.value === (value as string) ? 'bg-muted font-medium' : ''
                                }`}
                                onMouseDown={(e) => {
                                    e.preventDefault();
                                    handleSelect(opt.value);
                                }}
                            >
                                <div className="truncate">{opt.label}</div>
                            </li>
                        ))}
                    </ul>
                )}
                {isOpen && search && filtered.length === 0 && (
                    <p className="absolute z-50 mt-1 w-full rounded-md border border-input bg-popover px-3 py-2 text-sm text-muted-foreground shadow-md">
                        No repositories found
                    </p>
                )}
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
    );
}

function UrlListField({ field, value, error, onChange }: FieldRendererProps) {
    const urls: string[] = Array.isArray(value) ? value : [];
    const [input, setInput] = useState('');

    const addUrl = () => {
        const trimmed = input.trim();
        if (trimmed && !urls.includes(trimmed)) {
            onChange([...urls, trimmed]);
            setInput('');
        }
    };

    const removeUrl = (index: number) => {
        onChange(urls.filter((_: string, i: number) => i !== index));
    };

    return (
        <div className="space-y-2">
            <Label>{field.label}{field.required && <span className="text-red-500 ml-1">*</span>}</Label>
            {urls.length > 0 && (
                <ul className="space-y-1">
                    {urls.map((url, i) => (
                        <li key={i} className="flex items-center gap-2 rounded-md border border-input bg-muted/50 px-3 py-1.5 text-sm">
                            <span className="truncate flex-1">{url}</span>
                            <button
                                type="button"
                                onClick={() => removeUrl(i)}
                                className="shrink-0 text-muted-foreground hover:text-red-500 transition-colors"
                                aria-label={`Remove ${url}`}
                            >
                                &times;
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            <div className="flex gap-2">
                <Input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            addUrl();
                        }
                    }}
                    placeholder={field.placeholder || 'https://example.com/docs'}
                    className={error ? 'border-red-500' : ''}
                />
                <button
                    type="button"
                    onClick={addUrl}
                    disabled={!input.trim()}
                    className="shrink-0 rounded-md border border-input bg-muted px-3 py-2 text-sm hover:bg-muted/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    Add
                </button>
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
    );
}
