'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw,
  Plus,
  Trash2,
  Edit2,
  Power,
  PowerOff,
  Server,
  AlertCircle,
  Check,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { EmptyState } from '@/components/ui/empty-state';
import { AlertCard } from '@/components/ui/alert-card';
import {
  getMCPServers,
  addMCPServer,
  updateMCPServer,
  deleteMCPServer,
  toggleMCPServer,
  setMCPEnabled,
} from '@/lib/api/settings';
import type { MCPServerConfig, MCPSettingsResponse } from '@/lib/types/api';

const TRANSPORT_OPTIONS = ['streamable-http', 'stdio', 'sse'] as const;

const EMPTY_SERVER: MCPServerConfig = {
  id: '',
  name: '',
  transport: 'streamable-http',
  url: '',
  command: '',
  args: [],
  env: {},
  enabled: true,
  tools_filter: [],
};

export default function MCPSettingsPage() {
  const [settings, setSettings] = useState<MCPSettingsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  // Form state for adding/editing
  const [isEditing, setIsEditing] = useState(false);
  const [editingServer, setEditingServer] = useState<MCPServerConfig | null>(null);
  const [formData, setFormData] = useState<MCPServerConfig>(EMPTY_SERVER);

  const fetchSettings = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getMCPServers();
      setSettings(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load MCP settings';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleGlobalToggle = async () => {
    if (!settings) return;
    setSaveStatus('saving');
    try {
      await setMCPEnabled(!settings.enabled);
      setSettings((prev) => (prev ? { ...prev, enabled: !prev.enabled } : prev));
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 1500);
    } catch {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 2000);
    }
  };

  const handleServerToggle = async (serverId: string, currentEnabled: boolean) => {
    try {
      await toggleMCPServer(serverId, !currentEnabled);
      setSettings((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          servers: prev.servers.map((s) =>
            s.id === serverId ? { ...s, enabled: !currentEnabled } : s
          ),
        };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to toggle server');
    }
  };

  const handleDeleteServer = async (serverId: string) => {
    if (!confirm('Are you sure you want to delete this MCP server?')) return;
    try {
      await deleteMCPServer(serverId);
      setSettings((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          servers: prev.servers.filter((s) => s.id !== serverId),
        };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete server');
    }
  };

  const handleEditServer = (server: MCPServerConfig) => {
    setEditingServer(server);
    setFormData({ ...server });
    setIsEditing(true);
  };

  const handleAddNew = () => {
    setEditingServer(null);
    setFormData({ ...EMPTY_SERVER, id: `mcp-${Date.now()}` });
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditingServer(null);
    setFormData(EMPTY_SERVER);
  };

  const handleSaveServer = async () => {
    if (!formData.id || !formData.name) {
      setError('Server ID and Name are required');
      return;
    }

    setSaveStatus('saving');
    try {
      if (editingServer) {
        // Update existing
        await updateMCPServer(editingServer.id, formData);
        setSettings((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            servers: prev.servers.map((s) =>
              s.id === editingServer.id ? formData : s
            ),
          };
        });
      } else {
        // Add new
        await addMCPServer(formData);
        setSettings((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            servers: [...prev.servers, formData],
          };
        });
      }
      setSaveStatus('saved');
      setIsEditing(false);
      setEditingServer(null);
      setFormData(EMPTY_SERVER);
      setTimeout(() => setSaveStatus('idle'), 1500);
    } catch (err) {
      setSaveStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to save server');
      setTimeout(() => setSaveStatus('idle'), 2000);
    }
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">MCP Settings</h1>
          <p className="text-muted-foreground">
            Configure Model Context Protocol servers for extended tool capabilities
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

      {error && (
        <AlertCard
          variant="error"
          title={error}
          onDismiss={() => setError(null)}
        />
      )}

      {/* Global MCP Toggle */}
      <Card>
        <CardContent className="py-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-medium">MCP Integration</h3>
              <p className="text-sm text-muted-foreground">
                Globally enable or disable MCP tool integration
              </p>
            </div>
            <Switch
              checked={settings?.enabled ?? false}
              onCheckedChange={handleGlobalToggle}
              disabled={!settings}
            />
          </div>
        </CardContent>
      </Card>

      {/* Server List */}
      {isLoading ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            Loading MCP settings...
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-semibold">Configured Servers</h2>
            <Button onClick={handleAddNew} disabled={isEditing}>
              <Plus className="h-4 w-4 mr-2" />
              Add Server
            </Button>
          </div>

          {/* Add/Edit Form */}
          {isEditing && (
            <Card className="border-primary">
              <CardContent className="py-4 space-y-4">
                <h3 className="font-medium">
                  {editingServer ? 'Edit Server' : 'Add New Server'}
                </h3>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium">Server ID</label>
                    <Input
                      value={formData.id}
                      onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                      placeholder="my-mcp-server"
                      disabled={!!editingServer}
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium">Display Name</label>
                    <Input
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      placeholder="My MCP Server"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium">Transport</label>
                    <select
                      value={formData.transport}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          transport: e.target.value as MCPServerConfig['transport'],
                        })
                      }
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      {TRANSPORT_OPTIONS.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-sm font-medium">Enabled</label>
                    <Switch
                      checked={formData.enabled}
                      onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
                    />
                  </div>
                </div>

                {(formData.transport === 'streamable-http' || formData.transport === 'sse') && (
                  <div>
                    <label className="text-sm font-medium">URL</label>
                    <Input
                      value={formData.url || ''}
                      onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                      placeholder="http://localhost:8080/mcp"
                    />
                  </div>
                )}

                {formData.transport === 'stdio' && (
                  <>
                    <div>
                      <label className="text-sm font-medium">Command</label>
                      <Input
                        value={formData.command || ''}
                        onChange={(e) => setFormData({ ...formData, command: e.target.value })}
                        placeholder="mcp-filesystem"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium">Arguments (comma-separated)</label>
                      <Input
                        value={formData.args.join(', ')}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            args: e.target.value.split(',').map((a) => a.trim()).filter(Boolean),
                          })
                        }
                        placeholder="/data/repos, --readonly"
                      />
                    </div>
                  </>
                )}

                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" onClick={handleCancelEdit}>
                    Cancel
                  </Button>
                  <Button onClick={handleSaveServer}>
                    {editingServer ? 'Update' : 'Add'} Server
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Server Cards */}
          {settings?.servers.length === 0 ? (
            <EmptyState
              icon={Server}
              title="No MCP servers configured"
              description='Click "Add Server" to configure your first MCP server'
            />
          ) : (
            settings?.servers.map((server) => (
              <Card key={server.id} className={!server.enabled ? 'opacity-60' : ''}>
                <CardContent className="py-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Server className={`h-5 w-5 ${server.enabled ? 'text-primary' : 'text-muted-foreground'}`} />
                      <div>
                        <h3 className="font-medium">{server.name}</h3>
                        <p className="text-sm text-muted-foreground">
                          {server.id} • {server.transport}
                          {server.url && ` • ${server.url}`}
                          {server.command && ` • ${server.command}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleServerToggle(server.id, server.enabled)}
                        title={server.enabled ? 'Disable' : 'Enable'}
                      >
                        {server.enabled ? (
                          <Power className="h-4 w-4 text-green-600" />
                        ) : (
                          <PowerOff className="h-4 w-4 text-muted-foreground" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleEditServer(server)}
                        title="Edit"
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDeleteServer(server.id)}
                        title="Delete"
                        className="text-red-600 hover:text-red-700"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  );
}
