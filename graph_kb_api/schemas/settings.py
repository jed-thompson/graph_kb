"""
Pydantic schemas for settings endpoints.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    """Current settings response."""

    top_k: int
    max_depth: int
    model: str
    temperature: float
    auto_review: bool
    plan_max_llm_calls: int = 500
    plan_max_tokens: int = 500_000
    plan_max_wall_clock_s: int = 1800


class SettingsUpdateRequest(BaseModel):
    """Request body for updating settings. All fields are optional."""

    top_k: Optional[int] = Field(default=None, ge=5, le=5000)
    max_depth: Optional[int] = Field(default=None, ge=1, le=100)
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    auto_review: Optional[bool] = None
    plan_max_llm_calls: Optional[int] = Field(default=None, ge=1, le=10000)
    plan_max_tokens: Optional[int] = Field(default=None, ge=1000, le=10_000_000)
    plan_max_wall_clock_s: Optional[int] = Field(default=None, ge=60, le=7200)


class ModelOption(BaseModel):
    """A single model available for selection."""

    id: str
    name: str
    group: str


class ModelsResponse(BaseModel):
    """Available models grouped by family."""

    models: List[ModelOption]
    current: str


# ---------------------------------------------------------------------------
# MCP (Model Context Protocol) Configuration Schemas
# ---------------------------------------------------------------------------


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server connection."""

    id: str = Field(..., description="Unique identifier for this MCP server")
    name: str = Field(..., description="Display name for the MCP server")
    transport: str = Field(
        default="streamable-http",
        description="Transport type: 'stdio', 'sse', or 'streamable-http'",
    )
    url: Optional[str] = Field(
        default=None, description="URL for HTTP transports (required for sse/streamable-http)"
    )
    command: Optional[str] = Field(
        default=None, description="Command to run for stdio transport"
    )
    args: List[str] = Field(default_factory=list, description="Arguments for stdio transport")
    env: dict = Field(default_factory=dict, description="Environment variables for stdio transport")
    enabled: bool = Field(default=True, description="Whether this server is active")
    tools_filter: List[str] = Field(
        default_factory=list, description="List of tool names to enable (empty = all tools)"
    )


class MCPSettingsRequest(BaseModel):
    """Request to add or update an MCP server."""

    server: MCPServerConfig


class MCPSettingsResponse(BaseModel):
    """Response with all configured MCP servers."""

    servers: List[MCPServerConfig]
    enabled: bool = Field(..., description="Global MCP integration toggle")


class MCPToggleRequest(BaseModel):
    """Request to toggle a specific MCP server or global MCP."""

    enabled: bool
