'use client';

import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Check, AlertCircle, Settings as SettingsIcon, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { getSettings, updateSettings, getModels } from '@/lib/api/settings';
import type { Settings, SettingsUpdateRequest, ModelOption } from '@/lib/types/api';
import MCPSettingsPage from './mcp/page';

// Ranges that match the backend defaults and RetrievalConfig validation
const RANGES = {
    top_k: { min: 5, max: 5000, step: 5 },
    max_depth: { min: 1, max: 100, step: 1 },
    temperature: { min: 0, max: 2, step: 0.1 },
} as const;

interface ValidationErrors {
    top_k?: string;
    max_depth?: string;
    temperature?: string;
}

function validate(field: keyof Settings, value: number): string | undefined {
    switch (field) {
        case 'top_k': {
            const r = RANGES.top_k;
            if (!Number.isInteger(value) || value < r.min || value > r.max)
                return `top_k must be an integer between ${r.min} and ${r.max}`;
            break;
        }
        case 'max_depth': {
            const r = RANGES.max_depth;
            if (!Number.isInteger(value) || value < r.min || value > r.max)
                return `max_depth must be an integer between ${r.min} and ${r.max}`;
            break;
        }
        case 'temperature': {
            const r = RANGES.temperature;
            if (value < r.min || value > r.max)
                return `temperature must be between ${r.min} and ${r.max}`;
            break;
        }
    }
    return undefined;
}

// Group models by their group field for the select dropdown
function groupModels(models: ModelOption[]): Map<string, ModelOption[]> {
    const groups = new Map<string, ModelOption[]>();
    for (const m of models) {
        const list = groups.get(m.group) ?? [];
        list.push(m);
        groups.set(m.group, list);
    }
    return groups;
}

export default function SettingsPage() {
    const [settings, setSettings] = useState<Settings | null>(null);
    const [models, setModels] = useState<ModelOption[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [validationErrors, setValidationErrors] = useState<ValidationErrors>({});
    const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
    const [activeTab, setActiveTab] = useState<'general' | 'mcp'>('general');

    const fetchSettings = useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const [data, modelsData] = await Promise.all([getSettings(), getModels()]);
            setSettings(data);
            setModels(modelsData.models);
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to load settings';
            setError(message);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchSettings();
    }, [fetchSettings]);

    const persistField = useCallback(
        async (update: SettingsUpdateRequest) => {
            setSaveStatus('saving');
            try {
                const updated = await updateSettings(update);
                setSettings(updated);
                setSaveStatus('saved');
                setTimeout(() => setSaveStatus('idle'), 1500);
            } catch {
                setSaveStatus('error');
                setTimeout(() => setSaveStatus('idle'), 2000);
            }
        },
        []
    );

    const handleNumberChange = (
        field: 'top_k' | 'max_depth' | 'temperature',
        raw: string
    ) => {
        if (!settings) return;
        const value = field === 'temperature' ? parseFloat(raw) : parseInt(raw, 10);
        if (isNaN(value)) return;

        const err = validate(field, value);
        setValidationErrors((prev) => ({ ...prev, [field]: err }));
        setSettings((prev) => (prev ? { ...prev, [field]: value } : prev));

        if (!err) {
            persistField({ [field]: value });
        }
    };

    const handleSliderChange = (
        field: 'top_k' | 'max_depth' | 'temperature',
        values: number[]
    ) => {
        if (!settings) return;
        const value = values[0];
        setValidationErrors((prev) => ({ ...prev, [field]: undefined }));
        setSettings((prev) => (prev ? { ...prev, [field]: value } : prev));
        persistField({ [field]: value });
    };

    const handleModelChange = (value: string) => {
        if (!settings) return;
        setSettings((prev) => (prev ? { ...prev, model: value } : prev));
        persistField({ model: value });
    };

    const handleAutoReviewToggle = () => {
        if (!settings) return;
        const next = !settings.auto_review;
        setSettings((prev) => (prev ? { ...prev, auto_review: next } : prev));
        persistField({ auto_review: next });
    };

    const modelGroups = groupModels(models);

    return (
        <div className="container mx-auto py-6 space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold">Settings</h1>
                    <p className="text-muted-foreground">
                        Configure retrieval, LLM, and MCP parameters
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {saveStatus === 'saving' && (
                        <span className="text-sm text-muted-foreground">Saving...</span>
                    )}
                    {saveStatus === 'saved' && (
                        <span className="text-sm text-green-600 flex items-center gap-1">
                            <Check className="h-4 w-4" /> Saved
                        </span>
                    )}
                    {saveStatus === 'error' && (
                        <span className="text-sm text-red-600 flex items-center gap-1">
                            <AlertCircle className="h-4 w-4" /> Save failed
                        </span>
                    )}
                    <Button variant="outline" onClick={fetchSettings} disabled={isLoading}>
                        <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                </div>
            </div>

            {/* Tab Navigation */}
            <div className="border-b border-border">
                <nav className="flex gap-4">
                    <button
                        onClick={() => setActiveTab('general')}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                            activeTab === 'general'
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        <SettingsIcon className="h-4 w-4 inline-block mr-2" />
                        General
                    </button>
                    <button
                        onClick={() => setActiveTab('mcp')}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                            activeTab === 'mcp'
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        <Server className="h-4 w-4 inline-block mr-2" />
                        MCP Servers
                    </button>
                </nav>
            </div>

            {/* MCP Tab Content */}
            {activeTab === 'mcp' && <MCPSettingsPage />}

            {/* General Tab Content */}
            {activeTab === 'general' && error && (
                <Card className="border-red-200 bg-red-50 dark:bg-red-900/10">
                    <CardContent className="py-8 text-center text-red-600 dark:text-red-400">
                        <p className="font-medium">Error loading settings</p>
                        <p className="text-sm mt-2">{error}</p>
                        <Button variant="outline" className="mt-4" onClick={fetchSettings}>
                            Retry
                        </Button>
                    </CardContent>
                </Card>
            )}

            {activeTab === 'general' && !error && (isLoading || !settings) && (
                <Card>
                    <CardContent className="py-8 text-center text-muted-foreground">
                        Loading settings...
                    </CardContent>
                </Card>
            )}

            {activeTab === 'general' && !error && !isLoading && settings && (
                <div className="grid gap-6 max-w-2xl">
                    {/* top_k */}
                    <Card>
                        <CardContent className="py-4 space-y-3">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="font-medium">Top K</h3>
                                    <p className="text-sm text-muted-foreground">
                                        Number of results to retrieve ({RANGES.top_k.min}–{RANGES.top_k.max})
                                    </p>
                                </div>
                                <Input
                                    type="number"
                                    min={RANGES.top_k.min}
                                    max={RANGES.top_k.max}
                                    step={RANGES.top_k.step}
                                    value={settings.top_k}
                                    onChange={(e) => handleNumberChange('top_k', e.target.value)}
                                    className="w-24 text-right"
                                />
                            </div>
                            <Slider
                                min={RANGES.top_k.min}
                                max={RANGES.top_k.max}
                                step={RANGES.top_k.step}
                                value={[settings.top_k]}
                                onValueChange={(v) => handleSliderChange('top_k', v)}
                            />
                            {validationErrors.top_k && (
                                <p className="text-sm text-red-600">{validationErrors.top_k}</p>
                            )}
                        </CardContent>
                    </Card>

                    {/* max_depth */}
                    <Card>
                        <CardContent className="py-4 space-y-3">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="font-medium">Max Depth</h3>
                                    <p className="text-sm text-muted-foreground">
                                        Graph traversal depth ({RANGES.max_depth.min}–{RANGES.max_depth.max})
                                    </p>
                                </div>
                                <Input
                                    type="number"
                                    min={RANGES.max_depth.min}
                                    max={RANGES.max_depth.max}
                                    step={RANGES.max_depth.step}
                                    value={settings.max_depth}
                                    onChange={(e) => handleNumberChange('max_depth', e.target.value)}
                                    className="w-24 text-right"
                                />
                            </div>
                            <Slider
                                min={RANGES.max_depth.min}
                                max={RANGES.max_depth.max}
                                step={RANGES.max_depth.step}
                                value={[settings.max_depth]}
                                onValueChange={(v) => handleSliderChange('max_depth', v)}
                            />
                            {validationErrors.max_depth && (
                                <p className="text-sm text-red-600">{validationErrors.max_depth}</p>
                            )}
                        </CardContent>
                    </Card>

                    {/* model */}
                    <Card>
                        <CardContent className="py-4 space-y-2">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="font-medium">Model</h3>
                                    <p className="text-sm text-muted-foreground">
                                        LLM used for all workflows
                                    </p>
                                </div>
                                <select
                                    value={settings.model}
                                    onChange={(e) => handleModelChange(e.target.value)}
                                    className="flex h-10 w-64 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                                >
                                    {models.length === 0 ? (
                                        <option value={settings.model}>{settings.model}</option>
                                    ) : (
                                        <>
                                            {!models.some((m) => m.id === settings.model) && (
                                                <option value={settings.model}>{settings.model} (custom)</option>
                                            )}
                                            {Array.from(modelGroups.entries()).map(([group, groupModels]) => (
                                                <optgroup key={group} label={group}>
                                                    {groupModels.map((m) => (
                                                        <option key={m.id} value={m.id}>
                                                            {m.name}
                                                        </option>
                                                    ))}
                                                </optgroup>
                                            ))}
                                        </>
                                    )}
                                </select>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                Active: {settings.model}
                            </p>
                        </CardContent>
                    </Card>

                    {/* temperature */}
                    <Card>
                        <CardContent className="py-4 space-y-3">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="font-medium">Temperature</h3>
                                    <p className="text-sm text-muted-foreground">
                                        LLM sampling temperature ({RANGES.temperature.min}–{RANGES.temperature.max})
                                    </p>
                                </div>
                                <Input
                                    type="number"
                                    min={RANGES.temperature.min}
                                    max={RANGES.temperature.max}
                                    step={RANGES.temperature.step}
                                    value={settings.temperature}
                                    onChange={(e) => handleNumberChange('temperature', e.target.value)}
                                    className="w-24 text-right"
                                />
                            </div>
                            <Slider
                                min={RANGES.temperature.min}
                                max={RANGES.temperature.max}
                                step={RANGES.temperature.step}
                                value={[settings.temperature]}
                                onValueChange={(v) => handleSliderChange('temperature', v)}
                            />
                            {validationErrors.temperature && (
                                <p className="text-sm text-red-600">{validationErrors.temperature}</p>
                            )}
                        </CardContent>
                    </Card>

                    {/* auto_review */}
                    <Card>
                        <CardContent className="py-4">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="font-medium">Auto Review</h3>
                                    <p className="text-sm text-muted-foreground">
                                        Automatically review multi-agent workflow results
                                    </p>
                                </div>
                                <Switch
                                    checked={settings.auto_review}
                                    onCheckedChange={handleAutoReviewToggle}
                                />
                            </div>
                        </CardContent>
                    </Card>

                    {/* Plan Budget Defaults */}
                    <Card>
                        <CardContent className="py-4 space-y-3">
                            <div>
                                <h3 className="font-medium">Plan Budget Defaults</h3>
                                <p className="text-sm text-muted-foreground">
                                    Default resource limits for new plan sessions
                                </p>
                            </div>
                            <div className="grid grid-cols-3 gap-4">
                                <div className="space-y-1">
                                    <Label className="text-xs">Max LLM Calls</Label>
                                    <Input
                                        type="number"
                                        min={1}
                                        max={10000}
                                        value={settings.plan_max_llm_calls}
                                        onChange={(e) => {
                                            const v = parseInt(e.target.value, 10);
                                            if (!isNaN(v) && v >= 1) {
                                                setSettings((prev) => prev ? { ...prev, plan_max_llm_calls: v } : prev);
                                                persistField({ plan_max_llm_calls: v });
                                            }
                                        }}
                                        className="w-full"
                                    />
                                    <p className="text-[10px] text-muted-foreground">1–10,000</p>
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">Max Tokens</Label>
                                    <Input
                                        type="number"
                                        min={1000}
                                        max={10000000}
                                        step={10000}
                                        value={settings.plan_max_tokens}
                                        onChange={(e) => {
                                            const v = parseInt(e.target.value, 10);
                                            if (!isNaN(v) && v >= 1000) {
                                                setSettings((prev) => prev ? { ...prev, plan_max_tokens: v } : prev);
                                                persistField({ plan_max_tokens: v });
                                            }
                                        }}
                                        className="w-full"
                                    />
                                    <p className="text-[10px] text-muted-foreground">1k–10M</p>
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">Max Wall Clock (s)</Label>
                                    <Input
                                        type="number"
                                        min={60}
                                        max={7200}
                                        step={60}
                                        value={settings.plan_max_wall_clock_s}
                                        onChange={(e) => {
                                            const v = parseInt(e.target.value, 10);
                                            if (!isNaN(v) && v >= 60) {
                                                setSettings((prev) => prev ? { ...prev, plan_max_wall_clock_s: v } : prev);
                                                persistField({ plan_max_wall_clock_s: v });
                                            }
                                        }}
                                        className="w-full"
                                    />
                                    <p className="text-[10px] text-muted-foreground">60–7,200s</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}
        </div>
    );
}
