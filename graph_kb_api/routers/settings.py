"""
Settings management router.

Provides endpoints for reading and updating user settings
(top_k, max_depth, model, temperature, auto_review) and
listing available LLM models.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.schemas.settings import (
    MCPServerConfig,
    MCPSettingsRequest,
    MCPSettingsResponse,
    MCPToggleRequest,
    ModelOption,
    ModelsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])

# Default user id for single-user mode
_DEFAULT_USER = "default"

# Chat-capable models curated from OpenAIModel enum.
# Audio, image, embedding, TTS, whisper, moderation, and legacy models excluded.
_CHAT_MODELS = [
    (
        "GPT-3.5",
        [
            ("gpt-3.5-turbo", "GPT-3.5 Turbo"),
        ],
    ),
    (
        "GPT-4",
        [
            ("gpt-4", "GPT-4"),
            ("gpt-4-turbo", "GPT-4 Turbo"),
        ],
    ),
    (
        "GPT-4.1",
        [
            ("gpt-4.1", "GPT-4.1"),
            ("gpt-4.1-mini", "GPT-4.1 Mini"),
            ("gpt-4.1-nano", "GPT-4.1 Nano"),
        ],
    ),
    (
        "GPT-4o",
        [
            ("gpt-4o", "GPT-4o"),
            ("gpt-4o-mini", "GPT-4o Mini"),
        ],
    ),
    (
        "GPT-5",
        [
            ("gpt-5", "GPT-5"),
            ("gpt-5-mini", "GPT-5 Mini"),
            ("gpt-5-nano", "GPT-5 Nano"),
            ("gpt-5-pro", "GPT-5 Pro"),
        ],
    ),
    (
        "GPT-5.1",
        [
            ("gpt-5.1", "GPT-5.1"),
            ("gpt-5.1-codex", "GPT-5.1 Codex"),
            ("gpt-5.1-codex-max", "GPT-5.1 Codex Max"),
            ("gpt-5.1-codex-mini", "GPT-5.1 Codex Mini"),
        ],
    ),
    (
        "GPT-5.2",
        [
            ("gpt-5.2", "GPT-5.2"),
            ("gpt-5.2-pro", "GPT-5.2 Pro"),
        ],
    ),
    (
        "O-Series",
        [
            ("o1", "O1"),
            ("o1-pro", "O1 Pro"),
            ("o3", "O3"),
            ("o3-mini", "O3 Mini"),
            ("o4-mini", "O4 Mini"),
        ],
    ),
]


def _load_settings(facade) -> SettingsResponse:
    """Build a SettingsResponse from the metadata store and app config."""
    from graph_kb_api.config import settings as app_settings

    # Defaults from app config
    top_k = app_settings.retrieval_defaults.top_k_vector
    max_depth = app_settings.retrieval_defaults.max_depth
    model = app_settings.openai_model
    temperature = app_settings.llm_temperature
    auto_review = True

    # Override with persisted user preferences if available
    if facade.metadata_store is not None:
        prefs = facade.metadata_store.load_user_preferences(_DEFAULT_USER)
        if prefs is not None:
            top_k = prefs.top_k_vector
            max_depth = prefs.max_depth

    # Load extra settings (model, temperature, auto_review) from metadata store
    plan_max_llm_calls = 200
    plan_max_tokens = 500_000
    plan_max_wall_clock_s = 1800
    if facade.metadata_store is not None:
        extra = _load_extra_settings(facade.metadata_store)
        if extra.get("model") is not None:
            model = extra["model"]
        if extra.get("temperature") is not None:
            temperature = extra["temperature"]
        if extra.get("auto_review") is not None:
            auto_review = extra["auto_review"]
        if extra.get("plan_max_llm_calls") is not None:
            plan_max_llm_calls = extra["plan_max_llm_calls"]
        if extra.get("plan_max_tokens") is not None:
            plan_max_tokens = extra["plan_max_tokens"]
        if extra.get("plan_max_wall_clock_s") is not None:
            plan_max_wall_clock_s = extra["plan_max_wall_clock_s"]

    return SettingsResponse(
        top_k=top_k,
        max_depth=max_depth,
        model=model,
        temperature=temperature,
        auto_review=auto_review,
        plan_max_llm_calls=plan_max_llm_calls,
        plan_max_tokens=plan_max_tokens,
        plan_max_wall_clock_s=plan_max_wall_clock_s,
    )


def _load_extra_settings(metadata_store) -> dict:
    """Load model/temperature/auto_review from the metadata store."""
    try:
        data = metadata_store.load_raw_preferences(f"{_DEFAULT_USER}:extra")
        if data and isinstance(data, dict):
            return data
    except Exception:
        logger.debug("No extra settings found in metadata store")
    return {}


def _save_extra_settings(metadata_store, data: dict) -> None:
    """Persist model/temperature/auto_review into the metadata store."""
    try:
        metadata_store.save_raw_preferences(f"{_DEFAULT_USER}:extra", data)
    except Exception as e:
        logger.error(f"Failed to save extra settings: {e}")
        raise


def _apply_llm_settings(model: str | None, temperature: float | None) -> None:
    """Push model/temperature changes to the live LLMService singleton."""
    try:
        from graph_kb_api.context import _app_context

        if _app_context is None or _app_context.llm is None:
            return
        if model is not None:
            _app_context.llm.set_model(model)
        if temperature is not None:
            _app_context.llm.set_temperature(temperature)
    except Exception as e:
        logger.warning(f"Failed to apply LLM settings live: {e}")


@router.get("/models", response_model=ModelsResponse)
async def get_models(
    facade=Depends(get_graph_kb_facade),
) -> ModelsResponse:
    """Return available chat models and the currently active one."""
    current_settings = _load_settings(facade)
    models = []
    for group_name, group_models in _CHAT_MODELS:
        for model_id, display_name in group_models:
            models.append(ModelOption(id=model_id, name=display_name, group=group_name))
    return ModelsResponse(models=models, current=current_settings.model)


@router.get("", response_model=SettingsResponse)
async def get_settings(
    facade=Depends(get_graph_kb_facade),
) -> SettingsResponse:
    """Return current settings."""
    try:
        return _load_settings(facade)
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {e}")


@router.put("", response_model=SettingsResponse)
async def update_settings(
    request: SettingsUpdateRequest,
    facade=Depends(get_graph_kb_facade),
) -> SettingsResponse:
    """Update settings. Only provided (non-None) fields are changed."""
    try:
        if facade.metadata_store is None:
            raise HTTPException(status_code=503, detail="Metadata store unavailable")

        # --- Update retrieval-related fields (top_k, max_depth) ---
        if request.top_k is not None or request.max_depth is not None:
            from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

            prefs = facade.metadata_store.load_user_preferences(_DEFAULT_USER)
            if prefs is None:
                prefs = RetrievalConfig()

            if request.top_k is not None:
                prefs.top_k_vector = request.top_k
            if request.max_depth is not None:
                prefs.max_depth = request.max_depth

            facade.metadata_store.save_user_preferences(_DEFAULT_USER, prefs)

        # --- Update extra fields (model, temperature, auto_review, plan budget) ---
        if any(
            v is not None
            for v in [
                request.model,
                request.temperature,
                request.auto_review,
                request.plan_max_llm_calls,
                request.plan_max_tokens,
                request.plan_max_wall_clock_s,
            ]
        ):
            extra = _load_extra_settings(facade.metadata_store)
            if request.model is not None:
                extra["model"] = request.model
            if request.temperature is not None:
                extra["temperature"] = request.temperature
            if request.auto_review is not None:
                extra["auto_review"] = request.auto_review
            if request.plan_max_llm_calls is not None:
                extra["plan_max_llm_calls"] = request.plan_max_llm_calls
            if request.plan_max_tokens is not None:
                extra["plan_max_tokens"] = request.plan_max_tokens
            if request.plan_max_wall_clock_s is not None:
                extra["plan_max_wall_clock_s"] = request.plan_max_wall_clock_s
            _save_extra_settings(facade.metadata_store, extra)

        # --- Apply model/temperature to the live LLM service ---
        _apply_llm_settings(request.model, request.temperature)

        return _load_settings(facade)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {e}")


# ---------------------------------------------------------------------------
# MCP Settings Helper Functions
# ---------------------------------------------------------------------------


def _load_mcp_settings(metadata_store) -> dict:
    """Load MCP settings from the metadata store."""
    try:
        data = metadata_store.load_raw_preferences(f"{_DEFAULT_USER}:mcp")
        if data and isinstance(data, dict):
            return data
    except Exception:
        logger.debug("No MCP settings found in metadata store")
    return {"servers": [], "enabled": False}


def _save_mcp_settings(metadata_store, data: dict) -> None:
    """Persist MCP settings into the metadata store."""
    try:
        metadata_store.save_raw_preferences(f"{_DEFAULT_USER}:mcp", data)
    except Exception as e:
        logger.error(f"Failed to save MCP settings: {e}")
        raise


# ---------------------------------------------------------------------------
# MCP Settings Endpoints
# ---------------------------------------------------------------------------


@router.get("/mcp", response_model=MCPSettingsResponse)
async def get_mcp_settings(
    facade=Depends(get_graph_kb_facade),
) -> MCPSettingsResponse:
    """Get all configured MCP servers."""
    if facade.metadata_store is None:
        raise HTTPException(status_code=503, detail="Metadata store unavailable")

    data = _load_mcp_settings(facade.metadata_store)
    servers = [MCPServerConfig(**s) for s in data.get("servers", [])]
    return MCPSettingsResponse(servers=servers, enabled=data.get("enabled", False))


@router.post("/mcp", response_model=MCPServerConfig)
async def add_mcp_server(
    request: MCPSettingsRequest,
    facade=Depends(get_graph_kb_facade),
) -> MCPServerConfig:
    """Add a new MCP server connection."""
    if facade.metadata_store is None:
        raise HTTPException(status_code=503, detail="Metadata store unavailable")

    try:
        data = _load_mcp_settings(facade.metadata_store)

        # Check for duplicate ID
        if any(s.get("id") == request.server.id for s in data.get("servers", [])):
            raise HTTPException(
                status_code=400, detail=f"MCP server '{request.server.id}' already exists"
            )

        data["servers"].append(request.server.model_dump())
        _save_mcp_settings(facade.metadata_store, data)

        logger.info(f"Added MCP server: {request.server.id}")
        return request.server
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add MCP server: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add MCP server: {e}")


@router.put("/mcp/{server_id}", response_model=MCPServerConfig)
async def update_mcp_server(
    server_id: str,
    request: MCPSettingsRequest,
    facade=Depends(get_graph_kb_facade),
) -> MCPServerConfig:
    """Update an existing MCP server configuration."""
    if facade.metadata_store is None:
        raise HTTPException(status_code=503, detail="Metadata store unavailable")

    try:
        data = _load_mcp_settings(facade.metadata_store)
        servers = data.get("servers", [])

        # Find and update the server
        for i, s in enumerate(servers):
            if s.get("id") == server_id:
                # Preserve the original ID if not changed
                if request.server.id != server_id:
                    # Check for duplicate ID
                    if any(s2.get("id") == request.server.id for j, s2 in enumerate(servers) if j != i):
                        raise HTTPException(
                            status_code=400,
                            detail=f"MCP server '{request.server.id}' already exists",
                        )
                servers[i] = request.server.model_dump()
                _save_mcp_settings(facade.metadata_store, data)
                logger.info(f"Updated MCP server: {server_id}")
                return request.server

        raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update MCP server: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update MCP server: {e}")


@router.delete("/mcp/{server_id}")
async def delete_mcp_server(
    server_id: str,
    facade=Depends(get_graph_kb_facade),
):
    """Remove an MCP server."""
    if facade.metadata_store is None:
        raise HTTPException(status_code=503, detail="Metadata store unavailable")

    try:
        data = _load_mcp_settings(facade.metadata_store)
        original_count = len(data.get("servers", []))
        data["servers"] = [s for s in data.get("servers", []) if s.get("id") != server_id]

        if len(data["servers"]) == original_count:
            raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")

        _save_mcp_settings(facade.metadata_store, data)
        logger.info(f"Deleted MCP server: {server_id}")
        return {"deleted": server_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete MCP server: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete MCP server: {e}")


@router.put("/mcp/{server_id}/toggle")
async def toggle_mcp_server(
    server_id: str,
    request: MCPToggleRequest,
    facade=Depends(get_graph_kb_facade),
):
    """Enable/disable a specific MCP server."""
    if facade.metadata_store is None:
        raise HTTPException(status_code=503, detail="Metadata store unavailable")

    try:
        data = _load_mcp_settings(facade.metadata_store)

        for server in data.get("servers", []):
            if server.get("id") == server_id:
                server["enabled"] = request.enabled
                _save_mcp_settings(facade.metadata_store, data)
                logger.info(f"Toggled MCP server {server_id}: enabled={request.enabled}")
                return {"id": server_id, "enabled": request.enabled}

        raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to toggle MCP server: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to toggle MCP server: {e}")


@router.put("/mcp/enabled")
async def set_mcp_enabled(
    request: MCPToggleRequest,
    facade=Depends(get_graph_kb_facade),
):
    """Globally enable/disable MCP integration."""
    if facade.metadata_store is None:
        raise HTTPException(status_code=503, detail="Metadata store unavailable")

    try:
        data = _load_mcp_settings(facade.metadata_store)
        data["enabled"] = request.enabled
        _save_mcp_settings(facade.metadata_store, data)
        logger.info(f"MCP integration globally {'enabled' if request.enabled else 'disabled'}")
        return {"mcp_enabled": request.enabled}
    except Exception as e:
        logger.error(f"Failed to set MCP enabled: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set MCP enabled: {e}")
