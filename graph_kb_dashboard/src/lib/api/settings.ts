import { apiClient } from './client';
import type { Settings, SettingsUpdateRequest, ModelsResponse, MCPServerConfig, MCPSettingsResponse } from '@/lib/types/api';

export function getSettings(): Promise<Settings> {
  return apiClient.get<Settings>('/settings');
}

export function updateSettings(request: SettingsUpdateRequest): Promise<Settings> {
  return apiClient.put<Settings>('/settings', request);
}

export function getModels(): Promise<ModelsResponse> {
  return apiClient.get<ModelsResponse>('/settings/models');
}

export function getMcpSettings(): Promise<MCPSettingsResponse> {
  return apiClient.get<MCPSettingsResponse>('/settings/mcp');
}

export function addMcpServer(server: MCPServerConfig): Promise<MCPServerConfig> {
  return apiClient.post<MCPServerConfig>('/settings/mcp', { server });
}

export function updateMcpServer(serverId: string, server: MCPServerConfig): Promise<MCPServerConfig> {
  return apiClient.put<MCPServerConfig>(`/settings/mcp/${serverId}`, { server });
}

export function deleteMcpServer(serverId: string): Promise<{ deleted: string }> {
  return apiClient.delete<{ deleted: string }>(`/settings/mcp/${serverId}`);
}

export function toggleMcpServer(serverId: string, enabled: boolean): Promise<{ id: string; enabled: boolean }> {
  return apiClient.put<{ id: string; enabled: boolean }>(`/settings/mcp/${serverId}/toggle`, { enabled });
}

export function setMcpEnabled(enabled: boolean): Promise<{ mcp_enabled: boolean }> {
  return apiClient.put<{ mcp_enabled: boolean }>('/settings/mcp/enabled', { enabled });
}

// ---------------------------------------------------------------------------
// UPPERCASE aliases consumed by src/app/settings/mcp/page.tsx
// ---------------------------------------------------------------------------
export const getMCPServers = getMcpSettings;
export const addMCPServer = addMcpServer;
export const updateMCPServer = updateMcpServer;
export const deleteMCPServer = deleteMcpServer;
export const toggleMCPServer = toggleMcpServer;
export const setMCPEnabled = setMcpEnabled;
