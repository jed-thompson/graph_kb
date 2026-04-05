"""Graph statistics adapter for Neo4j queries."""

import json
from typing import Dict, List

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.stats import GraphStats
from ...storage.graph_store import Neo4jGraphStore
from ...storage.queries.stats_queries import (
    CALLS_DEPTH_TEMPLATE,
    CONTAINS_DEPTH_TEMPLATE,
    EDGE_COUNTS_QUERY,
    EXTENDS_DEPTH_TEMPLATE,
    IMPORTS_DEPTH_TEMPLATE,
    NODE_COUNTS_QUERY,
    SAMPLE_CHAINS_QUERY,
    SYMBOL_KINDS_QUERY,
)

logger = EnhancedLogger(__name__)


class GraphStatsAdapter:
    """Adapter for gathering graph statistics from Neo4j."""

    def __init__(self, graph_store: Neo4jGraphStore):
        """Initialize with an existing graph store.

        Args:
            graph_store: Initialized Neo4jGraphStore instance.
        """
        self._graph_store = graph_store
        self._config = graph_store._config

    def get_stats(self, repo_id: str) -> GraphStats:
        """Gather comprehensive statistics for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            GraphStats with node counts, edge counts, and depth analysis.
        """
        stats = GraphStats(repo_id=repo_id)

        with self._graph_store._session_manager.session() as session:
            stats.node_counts = self._get_node_counts(session, repo_id)
            stats.total_nodes = sum(stats.node_counts.values())

            stats.symbol_kinds = self._get_symbol_kinds(session, repo_id)

            stats.edge_counts = self._get_edge_counts(session, repo_id)
            stats.total_edges = sum(stats.edge_counts.values())

            stats.depth_analysis = self._get_depth_analysis(session, repo_id)
            stats.sample_chains = self._get_sample_chains(session, repo_id)

        return stats

    def _get_node_counts(self, session, repo_id: str) -> Dict[str, int]:
        """Get node counts by label for the repository."""
        counts = {}
        result = session.run(NODE_COUNTS_QUERY, repo_id=repo_id)

        for record in result:
            label = record["label"]
            count = record["count"]
            if count > 0:
                counts[label] = count

        return counts

    def _get_symbol_kinds(self, session, repo_id: str) -> Dict[str, int]:
        """Get symbol counts broken down by kind."""
        counts = {}
        result = session.run(SYMBOL_KINDS_QUERY, repo_id=repo_id)

        for record in result:
            kind = record["kind"]
            count = record["count"]
            if kind and count > 0:
                counts[kind] = count

        return counts

    def _get_edge_counts(self, session, repo_id: str) -> Dict[str, int]:
        """Get edge counts by relationship type."""
        counts = {}
        result = session.run(EDGE_COUNTS_QUERY, repo_id=repo_id)

        for record in result:
            rel_type = record["rel_type"]
            count = record["count"]
            if count > 0:
                counts[rel_type] = count

        return counts

    def _get_depth_analysis(self, session, repo_id: str) -> Dict[str, int]:
        """Analyze max traversal depth for key relationship types."""
        depths = {}

        depth_configs = [
            ("CALLS_max_depth", CALLS_DEPTH_TEMPLATE, 30),
            ("IMPORTS_max_depth", IMPORTS_DEPTH_TEMPLATE, 30),
            ("CONTAINS_max_depth", CONTAINS_DEPTH_TEMPLATE, 15),
            ("EXTENDS_max_depth", EXTENDS_DEPTH_TEMPLATE, 10),
        ]

        for key, template, max_search in depth_configs:
            max_depth = self._find_max_depth(session, repo_id, template, max_search)
            if max_depth != 0:
                depths[key] = max_depth

        return depths

    def _find_max_depth(
        self, session, repo_id: str, query_template: str, max_search_depth: int = 30
    ) -> int:
        """Find the maximum depth where paths exist.

        Returns negative value if depth reaches max_search_depth (indicating ≥max_search_depth).
        """
        max_found = 0
        consecutive_failures = 0

        for depth in range(1, max_search_depth + 1):
            try:
                query = (
                    query_template.format(depth=depth)
                    + " RETURN true as exists LIMIT 1"
                )
                result = session.run(query, repo_id=repo_id)
                record = result.single()

                if record:
                    max_found = depth
                    consecutive_failures = 0
                else:
                    break
            except Exception as e:
                logger.debug(f"Depth check failed at depth {depth}: {e}")
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    break

        if max_found >= max_search_depth:
            return -max_found

        return max_found

    def _get_sample_chains(self, session, repo_id: str, limit: int = 5) -> List[Dict]:
        """Get sample of longest call chains."""
        chains = []

        try:
            result = session.run(SAMPLE_CHAINS_QUERY, repo_id=repo_id, limit=limit)

            for record in result:
                start_attrs = (
                    json.loads(record["start_attrs"]) if record["start_attrs"] else {}
                )
                end_attrs = (
                    json.loads(record["end_attrs"]) if record["end_attrs"] else {}
                )

                chains.append(
                    {
                        "start": start_attrs.get("name", "unknown"),
                        "start_file": start_attrs.get("file_path", "").split("/")[-1],
                        "depth": record["depth"],
                        "end": end_attrs.get("name", "unknown"),
                        "end_file": end_attrs.get("file_path", "").split("/")[-1],
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to get sample chains: {e}")

        return chains
