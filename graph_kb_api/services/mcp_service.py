"""MCP (Model Context Protocol) Service for tool integration.

This service manages connections to MCP servers and provides a unified
interface for discovering and invoking MCP tools alongside native GraphKB tools.

Uses FastMCP for client connections with automatic transport inference.

Usage:
    mcp_service = MCPService(metadata_store)
    await mcp_service.connect_all()
    tools = mcp_service.get_tools_for_llm()
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from fastmcp import Client
from fastmcp.client.transports import (
    PythonStdioTransport,
    SSETransport,
)

from graph_kb_api.schemas.settings import MCPServerConfig

if TYPE_CHECKING:
    from graph_kb_api.graph_kb.storage import MetadataStore

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Represents a tool discovered from an MCP server."""

    name: str
    """Full tool name including server prefix (e.g., 'web-search__search')."""

    original_name: str
    """Original tool name from the MCP server."""

    server_id: str
    """ID of the MCP server this tool belongs to."""

    description: str
    """Tool description from the MCP server."""

    input_schema: Dict[str, Any]
    """JSON schema for the tool's input parameters."""

    handler: Optional[Callable] = None
    """Handler function for invoking the tool."""


class MCPConnectionError(Exception):
    """Raised when connection to an MCP server fails."""
    pass


class MCPToolInvocationError(Exception):
    """Raised when tool invocation fails."""
    pass


class MCPService:
    """Service for managing MCP server connections and tool discovery.

    This service:
    - Loads MCP server configurations from the metadata store
    - Establishes connections to MCP servers
    - Discovers available tools from each server
    - Provides tool schemas formatted for LLM function calling
    - Routes tool invocations to the appropriate MCP server
    """

    def __init__(self, metadata_store: Optional["MetadataStore"] = None):
        """Initialize the MCP service.

        Args:
            metadata_store: The metadata store for loading MCP configurations.
        """
        self.metadata_store = metadata_store
        self.servers: List[MCPServerConfig] = []
        self.tools: Dict[str, MCPTool] = {}
        self._sessions: Dict[str, Any] = {}
        self._connected = False

    def load_configured_servers(self) -> List[MCPServerConfig]:
        """Load MCP server configurations from the metadata store.

        Returns:
            List of enabled MCP server configurations.
        """
        if self.metadata_store is None:
            logger.debug("No metadata store available for MCP configuration")
            return []

        try:
            data = self.metadata_store.load_raw_preferences("default:mcp")
            if not data or not isinstance(data, dict):
                return []

            if not data.get("enabled", False):
                logger.info("MCP integration is globally disabled")
                return []

            servers = []
            for server_data in data.get("servers", []):
                try:
                    server = MCPServerConfig(**server_data)
                    if server.enabled:
                        servers.append(server)
                    else:
                        logger.debug(f"MCP server '{server.id}' is disabled, skipping")
                except Exception as e:
                    logger.warning(f"Invalid MCP server config: {e}")

            self.servers = servers
            logger.info(f"Loaded {len(servers)} enabled MCP servers")
            return servers

        except Exception as e:
            logger.error(f"Failed to load MCP configuration: {e}")
            return []

    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all enabled MCP servers and discover tools.

        Returns:
            Dict mapping server IDs to connection success status.
        """
        results = {}
        self.tools = {}

        servers = self.load_configured_servers()
        if not servers:
            logger.info("No MCP servers to connect to")
            return results

        # Connect to each server in parallel
        connection_tasks = [self._connect_server(server) for server in servers]
        connection_results = await asyncio.gather(*connection_tasks, return_exceptions=True)

        for server, result in zip(servers, connection_results):
            if isinstance(result, Exception):
                logger.error(f"Failed to connect to MCP server '{server.id}': {result}")
                results[server.id] = False
            else:
                results[server.id] = True

        self._connected = any(results.values())
        return results

    async def _connect_server(self, config: MCPServerConfig) -> None:
        """Connect to a single MCP server and discover its tools.

        Args:
            config: The MCP server configuration.

        Raises:
            MCPConnectionError: If connection fails.
        """
        logger.info(f"Connecting to MCP server: {config.id} ({config.transport})")

        try:
            if config.transport == "streamable-http":
                await self._connect_http_server(config)
            elif config.transport == "stdio":
                await self._connect_stdio_server(config)
            elif config.transport == "sse":
                await self._connect_sse_server(config)
            else:
                raise MCPConnectionError(f"Unknown transport: {config.transport}")

            logger.info(f"Successfully connected to MCP server: {config.id}")

        except Exception as e:
            raise MCPConnectionError(f"Failed to connect to {config.id}: {e}") from e

    async def _connect_http_server(self, config: MCPServerConfig) -> None:
        """Connect to an MCP server via streamable-http transport using FastMCP.

        FastMCP automatically handles the HTTP/SSE transport based on the URL.
        """
        if not config.url:
            raise MCPConnectionError(f"HTTP server '{config.id}' requires a URL")

        logger.info(f"Connecting to HTTP MCP server '{config.id}' at {config.url}")

        # Create FastMCP client with automatic transport inference
        client = Client(config.url)

        try:
            # Enter the async context manager
            await client.__aenter__()
            self._sessions[config.id] = {
                "type": "http",
                "client": client,
                "connected": True,
            }

            # Discover tools from the server
            await self._discover_tools(config.id, client)
            logger.info(f"Connected to HTTP MCP server '{config.id}'")

        except Exception as e:
            # Clean up on failure
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
            raise MCPConnectionError(f"Failed to connect to HTTP server '{config.id}': {e}") from e

    async def _connect_stdio_server(self, config: MCPServerConfig) -> None:
        """Connect to an MCP server via stdio transport using FastMCP.

        Spawns a subprocess and communicates via stdin/stdout.
        """
        if not config.command:
            raise MCPConnectionError(f"Stdio server '{config.id}' requires a command")

        logger.info(f"Connecting to stdio MCP server '{config.id}' with command: {config.command}")

        # Create FastMCP client with stdio transport
        transport = PythonStdioTransport(
            command=config.command,
            args=config.args,
            env=config.env or None,
        )
        client = Client(transport)

        try:
            await client.__aenter__()
            self._sessions[config.id] = {
                "type": "stdio",
                "client": client,
                "connected": True,
            }

            await self._discover_tools(config.id, client)
            logger.info(f"Connected to stdio MCP server '{config.id}'")

        except Exception as e:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
            raise MCPConnectionError(f"Failed to connect to stdio server '{config.id}': {e}") from e

    async def _connect_sse_server(self, config: MCPServerConfig) -> None:
        """Connect to an MCP server via SSE transport using FastMCP."""
        if not config.url:
            raise MCPConnectionError(f"SSE server '{config.id}' requires a URL")

        logger.info(f"Connecting to SSE MCP server '{config.id}' at {config.url}")

        # Create FastMCP client with SSE transport
        transport = SSETransport(config.url)
        client = Client(transport)

        try:
            await client.__aenter__()
            self._sessions[config.id] = {
                "type": "sse",
                "client": client,
                "connected": True,
            }

            await self._discover_tools(config.id, client)
            logger.info(f"Connected to SSE MCP server '{config.id}'")

        except Exception as e:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
            raise MCPConnectionError(f"Failed to connect to SSE server '{config.id}': {e}") from e

    async def _discover_tools(self, server_id: str, client: Client) -> None:
        """Discover and register tools from a connected MCP server.

        Args:
            server_id: The server ID for tool name prefixing.
            client: The connected FastMCP client.
        """
        try:
            tools = await client.list_tools()
            logger.info(f"Discovered {len(tools)} tools from MCP server '{server_id}'")

            for tool in tools:
                # Apply tools_filter if configured
                server_config = next((s for s in self.servers if s.id == server_id), None)
                if server_config and server_config.tools_filter:
                    if tool.name not in server_config.tools_filter:
                        logger.debug(f"Tool '{tool.name}' filtered out for server '{server_id}'")
                        continue

                # Extract input schema
                input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {}

                # Register the tool with server prefix
                self.register_tool(
                    server_id=server_id,
                    tool_name=tool.name,
                    description=tool.description or f"MCP tool: {tool.name}",
                    input_schema=input_schema,
                    handler=None,  # Will use client.call_tool in invoke_tool
                )

        except Exception as e:
            logger.warning(f"Failed to discover tools from '{server_id}': {e}")

    def register_tool(
        self,
        server_id: str,
        tool_name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Optional[Callable] = None,
    ) -> None:
        """Register a tool discovered from an MCP server.

        Args:
            server_id: The MCP server ID.
            tool_name: The original tool name from the server.
            description: Tool description.
            input_schema: JSON schema for input parameters.
            handler: Optional handler function for tool invocation.
        """
        # Prefix tool name with server ID to avoid collisions
        full_name = f"{server_id}__{tool_name}"

        self.tools[full_name] = MCPTool(
            name=full_name,
            original_name=tool_name,
            server_id=server_id,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )

        logger.debug(f"Registered MCP tool: {full_name}")

    def get_schemas_for_llm(self) -> List[Dict[str, Any]]:
        """Get tool schemas formatted for LLM function calling.

        Returns:
            List of tool schemas in OpenAI function calling format.
        """
        schemas = []
        for tool in self.tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            })
        return schemas

    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """Alias for get_schemas_for_llm() for compatibility."""
        return self.get_schemas_for_llm()

    async def invoke_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Invoke an MCP tool by name using the FastMCP client.

        Args:
            tool_name: The full tool name (including server prefix).
            arguments: The arguments to pass to the tool.

        Returns:
            The result from the tool invocation.

        Raises:
            MCPToolInvocationError: If tool invocation fails.
        """
        tool = self.tools.get(tool_name)
        if tool is None:
            raise MCPToolInvocationError(f"Tool '{tool_name}' not found")

        # Get the session for this tool's server
        session = self._sessions.get(tool.server_id)
        if not session or not session.get("connected"):
            raise MCPToolInvocationError(
                f"MCP server '{tool.server_id}' is not connected"
            )

        client = session.get("client")
        if not client:
            raise MCPToolInvocationError(
                f"No client available for MCP server '{tool.server_id}'"
            )

        try:
            logger.debug(f"Invoking MCP tool: {tool_name} with args: {arguments}")
            # Use the original tool name (without server prefix) for the actual call
            result = await client.call_tool(tool.original_name, arguments)
            return result
        except Exception as e:
            raise MCPToolInvocationError(f"Tool '{tool_name}' invocation failed: {e}") from e

    def is_connected(self) -> bool:
        """Check if any MCP servers are connected."""
        return self._connected

    def get_server_status(self) -> Dict[str, Dict[str, Any]]:
        """Get connection status for all configured servers.

        Returns:
            Dict mapping server IDs to their connection status.
        """
        status = {}
        for server in self.servers:
            session = self._sessions.get(server.id, {})
            status[server.id] = {
                "name": server.name,
                "transport": server.transport,
                "connected": session.get("connected", False),
                "tools_count": sum(
                    1 for t in self.tools.values() if t.server_id == server.id
                ),
            }
        return status

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers by closing FastMCP clients."""
        for server_id, session in list(self._sessions.items()):
            try:
                client = session.get("client")
                if client:
                    await client.__aexit__(None, None, None)
                logger.info(f"Disconnected from MCP server: {server_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting from {server_id}: {e}")

        self._sessions = {}
        self.tools = {}
        self._connected = False

    async def refresh(self) -> Dict[str, bool]:
        """Refresh connections to all MCP servers.

        Disconnects from all servers and reconnects.

        Returns:
            Dict mapping server IDs to connection success status.
        """
        await self.disconnect_all()
        return await self.connect_all()


# Singleton instance for application-wide access
_mcp_service_instance: Optional[MCPService] = None


def get_mcp_service() -> Optional[MCPService]:
    """Get the global MCP service instance."""
    return _mcp_service_instance


def set_mcp_service(service: Optional[MCPService]) -> None:
    """Set the global MCP service instance."""
    global _mcp_service_instance
    _mcp_service_instance = service
