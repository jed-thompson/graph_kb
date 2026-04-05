"""
Graph KB API Configuration — single source of truth.

All config comes from env vars / .env via pydantic-settings.
"""

from graph_kb_api.config.settings import (
    DEFAULT_EMBEDDING_CONFIG,
    EMBEDDING_MODEL_CONFIGS,
    ChatUISliders,
    RetrievalDefaults,
    Settings,
    SliderConfig,
    settings,
)


def get_settings() -> Settings:
    """Simple getter for main.py compatibility."""
    return settings


__all__ = [
    "settings",
    "Settings",
    "get_settings",
    "EMBEDDING_MODEL_CONFIGS",
    "DEFAULT_EMBEDDING_CONFIG",
    "RetrievalDefaults",
    "ChatUISliders",
    "SliderConfig",
]
