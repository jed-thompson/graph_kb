"""Adapter-related data models.

This module contains data models specific to adapter patterns and external service integration.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class AdapterType(Enum):
    """Types of adapters in the system."""
    STORAGE = "storage"
    EXTERNAL = "external"
    RETRIEVAL = "retrieval"
    EMBEDDING = "embedding"
    LLM = "llm"


class AdapterStatus(Enum):
    """Status of adapter connections."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    INITIALIZING = "initializing"


@dataclass
class AdapterConfig:
    """Configuration for adapter initialization."""
    adapter_type: AdapterType
    name: str
    enabled: bool = True
    config_params: Dict[str, Any] = None
    timeout: float = 30.0
    retry_attempts: int = 3

    def __post_init__(self):
        if self.config_params is None:
            self.config_params = {}


@dataclass
class AdapterHealth:
    """Health status information for an adapter."""
    adapter_name: str
    adapter_type: AdapterType
    status: AdapterStatus
    last_check: Optional[str] = None
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class StorageAdapterMetrics:
    """Metrics for storage adapters."""
    connection_pool_size: int = 0
    active_connections: int = 0
    query_count: int = 0
    average_query_time: float = 0.0
    error_count: int = 0
    last_error: Optional[str] = None


@dataclass
class ExternalAdapterMetrics:
    """Metrics for external service adapters."""
    api_calls_count: int = 0
    success_rate: float = 0.0
    average_response_time: float = 0.0
    rate_limit_remaining: Optional[int] = None
    last_error: Optional[str] = None
    quota_usage: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.quota_usage is None:
            self.quota_usage = {}


@dataclass
class AdapterRegistry:
    """Registry of all adapters in the system."""
    storage_adapters: List[str] = None
    external_adapters: List[str] = None
    adapter_configs: Dict[str, AdapterConfig] = None
    adapter_health: Dict[str, AdapterHealth] = None

    def __post_init__(self):
        if self.storage_adapters is None:
            self.storage_adapters = []
        if self.external_adapters is None:
            self.external_adapters = []
        if self.adapter_configs is None:
            self.adapter_configs = {}
        if self.adapter_health is None:
            self.adapter_health = {}
