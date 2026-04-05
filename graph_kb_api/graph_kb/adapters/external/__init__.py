"""External service adapters for Graph KB system.

This module contains adapters that abstract external service access,
providing clean interfaces for LLM services, embedding services,
and other external APIs.
"""

from .embedder_adapter import EmbedderAdapter
from .llm_adapter import LLMAdapter

__all__ = [
    "LLMAdapter",
    "EmbedderAdapter",
]
