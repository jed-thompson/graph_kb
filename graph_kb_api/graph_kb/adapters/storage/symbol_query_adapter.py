"""Adapter for symbol query operations.

This module implements the SymbolQueryAdapter, which encapsulates symbol search
patterns moved from GraphQueryService and GraphRAGService. The adapter uses the
Neo4jGraphStore facade's internal session manager to execute symbol queries.
"""

import json
import re
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...storage.graph_store import Neo4jGraphStore
from ...storage.queries.symbol_queries import SymbolQueries
from .interfaces import ISymbolQueryAdapter

logger = EnhancedLogger(__name__)


class SymbolQueryAdapter(ISymbolQueryAdapter):
    """Encapsulates symbol query patterns.

    Moves symbol queries from GraphQueryService and GraphRAGService
    to this adapter. Services use this adapter instead of accessing
    the driver directly.
    """

    def __init__(self, graph_store: Neo4jGraphStore):
        """Initialize the SymbolQueryAdapter.

        Args:
            graph_store: The Neo4jGraphStore facade for graph access.
        """
        self._graph_store = graph_store

    def get_symbols_by_pattern(
        self,
        repo_id: str,
        name_pattern: Optional[str] = None,
        file_pattern: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get symbols matching specified patterns.

        This implementation is moved from GraphQueryService.get_symbols_by_pattern().

        Args:
            repo_id: The repository ID.
            name_pattern: Regex pattern for symbol name.
            file_pattern: Regex pattern for file path.
            kind: Symbol kind filter (function, class, method).
            limit: Maximum number of results.

        Returns:
            List of dictionaries with symbol information.
        """
        try:
            # Use internal session manager (adapters are allowed to access this)
            with self._graph_store._session_manager.session() as session:
                # Use query from SymbolQueries
                result = session.run(
                    SymbolQueries.GET_SYMBOLS_BY_PATTERN,
                    repo_id=repo_id,
                    limit=limit * 2
                )

                matches = []
                for record in result:
                    attrs = self._graph_store._deserialize_attrs(record["attrs"])
                    name = attrs.get("name", "")
                    file_path = attrs.get("file_path", "")
                    symbol_kind = attrs.get("kind", "")

                    # Apply filters
                    if name_pattern and not re.search(name_pattern, name, re.IGNORECASE):
                        continue
                    if file_pattern and not re.search(file_pattern, file_path, re.IGNORECASE):
                        continue
                    if kind and symbol_kind.lower() != kind.lower():
                        continue

                    matches.append({
                        "id": record["id"],
                        "name": name,
                        "kind": symbol_kind,
                        "file_path": file_path,
                        "docstring": attrs.get("docstring"),
                    })

                    if len(matches) >= limit:
                        break

                return matches

        except Exception as e:
            logger.error(f"Failed to get symbols by pattern: {e}")
            return []

    def search_symbols_by_name(
        self,
        repo_id: str,
        name: str,
    ) -> List[str]:
        """Search for symbols by name in the graph.

        This implementation is moved from GraphRAGService._search_symbols_by_name().

        Args:
            repo_id: The repository ID.
            name: The symbol name to search for.

        Returns:
            List of matching symbol IDs.
        """
        logger.debug(
            "searching symbols by name",
            data={"repo_id": repo_id, "name": name}
        )

        # Escape special characters in name for JSON string matching
        # Replace quotes and backslashes to prevent JSON injection
        escaped_name = name.replace('\\', '\\\\').replace('"', '\\"')
        escaped_name_lower = name.lower().replace('\\', '\\\\').replace('"', '\\"')

        try:
            # Use internal session manager (adapters are allowed to access this)
            with self._graph_store._session_manager.session() as session:
                logger.debug(
                    "before running query",
                    data={"repo_id": repo_id, "name": name,
                     "name_pattern1": f'"name": "{escaped_name}"',
                     "name_pattern2": f'"name": "{escaped_name_lower}"'}
                )

                # Use query from SymbolQueries
                result = session.run(
                    SymbolQueries.SEARCH_BY_NAME,
                    repo_id=repo_id,
                    name_pattern1=f'"name": "{escaped_name}"',  # Exact match
                    name_pattern2=f'"name": "{escaped_name_lower}"',  # Lowercase exact match
                )
                symbol_ids = []
                name_lower = name.lower()
                record_count = 0
                for record in result:
                    record_count += 1
                    node_id = record["id"]
                    # Verify the node actually exists and has the name
                    attrs_str = record.get("attrs", "{}")
                    if attrs_str:
                        # Parse attrs to verify name match with exact comparison
                        try:
                            attrs = json.loads(attrs_str) if isinstance(attrs_str, str) else attrs_str
                            symbol_name = attrs.get("name", "")
                            symbol_name_lower = symbol_name.lower()

                            # Use exact match (case-insensitive) or allow partial match only at word boundaries
                            # This prevents "main" from matching "domain" or "remain"
                            if symbol_name_lower == name_lower:
                                symbol_ids.append(node_id)
                            elif name_lower in symbol_name_lower:
                                # Partial match: check if it's at word boundaries
                                # This allows "generate" to match "generate_money" but not "regenerate"
                                pattern = r'\b' + re.escape(name_lower) + r'\b'
                                if re.search(pattern, symbol_name_lower):
                                    symbol_ids.append(node_id)
                        except Exception:
                            # Fallback: if JSON parsing fails, use string matching
                            # But be more strict - require word boundary
                            pattern = r'\b' + re.escape(name_lower) + r'\b'
                            if re.search(pattern, attrs_str.lower()):
                                symbol_ids.append(node_id)

                logger.debug(
                    "query completed",
                    data={"repo_id": repo_id, "name": name, "record_count": record_count,
                     "symbol_ids_count": len(symbol_ids), "symbol_ids": symbol_ids[:3]}
                )

                return symbol_ids
        except Exception as e:
            logger.error(
                "search exception",
                data={"repo_id": repo_id, "name": name, "error": str(e),
                 "error_type": type(e).__name__}
            )
            logger.debug("Symbol search failed for %s: %s", name, e)
            return []
