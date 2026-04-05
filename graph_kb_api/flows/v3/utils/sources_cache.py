"""
Sources cache for storing and retrieving source data.

This module provides a simple in-memory cache for storing sources
that can be retrieved by workflow_id for the sources page.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CachedSources:
    """Cached sources entry."""
    sources: List[Dict[str, Any]]
    total_count: int
    repo_id: str
    query: str
    created_at: float = field(default_factory=time.time)


class SourcesCache:
    """
    Thread-safe in-memory cache for sources.

    Sources are stored by workflow_id and automatically expire after
    a configurable TTL (default: 1 hour).
    """

    _instance: Optional['SourcesCache'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'SourcesCache':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: Dict[str, CachedSources] = {}
                    cls._instance._ttl = 3600  # 1 hour default TTL
        return cls._instance

    def store(
        self,
        workflow_id: str,
        sources: List[Dict[str, Any]],
        total_count: int,
        repo_id: str,
        query: str
    ) -> None:
        """
        Store sources in the cache.

        Args:
            workflow_id: Unique identifier for the workflow
            sources: List of source dictionaries
            total_count: Total number of sources (may be more than len(sources))
            repo_id: Repository identifier
            query: User's query
        """
        self._cleanup_expired()
        self._cache[workflow_id] = CachedSources(
            sources=sources,
            total_count=total_count,
            repo_id=repo_id,
            query=query,
        )

    def get(self, workflow_id: str) -> Optional[CachedSources]:
        """
        Retrieve sources from the cache.

        Args:
            workflow_id: Unique identifier for the workflow

        Returns:
            CachedSources if found and not expired, None otherwise
        """
        entry = self._cache.get(workflow_id)
        if entry is None:
            return None

        # Check if expired
        if time.time() - entry.created_at > self._ttl:
            del self._cache[workflow_id]
            return None

        return entry

    def delete(self, workflow_id: str) -> None:
        """Remove sources from the cache."""
        self._cache.pop(workflow_id, None)

    def _cleanup_expired(self) -> None:
        """Remove expired entries from the cache."""
        current_time = time.time()
        expired_keys = [
            k for k, v in self._cache.items()
            if current_time - v.created_at > self._ttl
        ]
        for key in expired_keys:
            del self._cache[key]

    def clear(self) -> None:
        """Clear all cached sources."""
        self._cache.clear()


# Global singleton instance
sources_cache = SourcesCache()
