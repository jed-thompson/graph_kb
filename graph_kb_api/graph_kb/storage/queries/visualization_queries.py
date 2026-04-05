"""Cypher queries for graph visualization operations.

All queries used by GraphQuerier for generating visualizations of
repositories, call chains, dependencies, hotspots, and architecture.
"""

from typing import Optional


class VisualizationQueries:
    """Centralized Cypher queries for visualization operations."""

    # =========================================================================
    # Architecture Queries
    # =========================================================================

    ARCHITECTURE_REPO = """
        MATCH (r:Repo {repo_id: $repo_id})
        RETURN r.id as id, r.attrs as attrs
    """

    ARCHITECTURE_FILES = """
        MATCH (f:File {repo_id: $repo_id})
        RETURN f.id as id, f.attrs as attrs
    """

    ARCHITECTURE_SYMBOLS = """
        MATCH (s:Symbol {repo_id: $repo_id})
        RETURN s.id as id, s.attrs as attrs
    """

    ARCHITECTURE_CONTAINS = """
        MATCH (f:File {repo_id: $repo_id})-[:CONTAINS]->(s:Symbol)
        RETURN f.id as file_id, s.id as symbol_id
    """

    ARCHITECTURE_RELATIONSHIPS_TEMPLATE = """
        MATCH path = (s1:Symbol {{repo_id: $repo_id}})-[:{rel_type}*1..{max_depth}]->(s2:Symbol)
        WITH s1, s2, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r) as from_node, endNode(r) as to_node, type(r) as rel_type
        RETURN from_node.id as from_id, to_node.id as to_id, rel_type
        LIMIT $limit
    """

    # =========================================================================
    # Folder/Path Queries
    # =========================================================================

    PATH_EXISTS = """
        MATCH (f:File {repo_id: $repo_id})
        WHERE f.attrs CONTAINS $path_pattern
        RETURN count(f) > 0 as exists
        LIMIT 1
    """

    # =========================================================================
    # Call Chain Queries
    # =========================================================================

    CALLS_FROM_ENTRY_POINT_TEMPLATE = """
        MATCH (start:Symbol {{repo_id: $repo_id}})
        WHERE start.attrs CONTAINS $symbol_pattern
        MATCH path = (start)-[:CALLS*1..{max_depth}]->(callee:Symbol)
        WITH start, callee, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r) as from_node, endNode(r) as to_node
        RETURN from_node.id as from_id, from_node.attrs as from_attrs,
               to_node.id as to_id, to_node.attrs as to_attrs
        LIMIT $limit
    """

    CALLS_RECURSIVE_TEMPLATE = """
        MATCH path = (s1:Symbol {{repo_id: $repo_id}})-[:CALLS*1..{max_depth}]->(s2:Symbol)
        WITH s1, s2, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r) as from_node, endNode(r) as to_node
        RETURN from_node.id as from_id, from_node.attrs as from_attrs,
               to_node.id as to_id, to_node.attrs as to_attrs
        LIMIT $limit
    """

    CALL_CHAIN_INCOMING_TEMPLATE = """
        MATCH (start:Symbol {{repo_id: $repo_id}})
        WHERE start.attrs CONTAINS $symbol_pattern
        MATCH path = (caller:Symbol)-[:CALLS*1..{max_depth}]->(start)
        WITH caller, start, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r) as from_node, endNode(r) as to_node
        RETURN from_node.id as from_id, from_node.attrs as from_attrs,
               to_node.id as to_id, to_node.attrs as to_attrs
        LIMIT $limit
    """

    CALL_CHAIN_OUTGOING_TEMPLATE = """
        MATCH (start:Symbol {{repo_id: $repo_id}})
        WHERE start.attrs CONTAINS $symbol_pattern
        MATCH path = (start)-[:CALLS*1..{max_depth}]->(callee:Symbol)
        WITH start, callee, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r) as from_node, endNode(r) as to_node
        RETURN from_node.id as from_id, from_node.attrs as from_attrs,
               to_node.id as to_id, to_node.attrs as to_attrs
        LIMIT $limit
    """

    # =========================================================================
    # Hotspot Queries
    # =========================================================================

    HOTSPOTS_HIGH_DEGREE = """
        MATCH (s:Symbol {repo_id: $repo_id})
        OPTIONAL MATCH (s)-[out:CALLS]->()
        OPTIONAL MATCH ()-[in:CALLS]->(s)
        WITH s, count(DISTINCT out) as outgoing, count(DISTINCT in) as incoming
        WHERE outgoing + incoming >= $min_connections
        RETURN s.id as id, s.attrs as attrs,
               outgoing, incoming, outgoing + incoming as total
        ORDER BY total DESC
        LIMIT $top_n
    """

    HOTSPOTS_EDGES = """
        MATCH (s1:Symbol {repo_id: $repo_id})-[r:CALLS]->(s2:Symbol)
        WHERE s1.id IN $hotspot_ids AND s2.id IN $hotspot_ids
        RETURN s1.id as from_id, s2.id as to_id
    """

    # =========================================================================
    # Symbol Neighborhood Queries
    # =========================================================================

    SYMBOL_NEIGHBORHOOD_TEMPLATE = """
        MATCH (start:Symbol {{repo_id: $repo_id}})
        WHERE start.attrs CONTAINS $symbol_pattern
        MATCH path = (start)-[*1..{max_depth}]-(neighbor:Symbol)
        WITH DISTINCT start, neighbor, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r) as from_node, endNode(r) as to_node, type(r) as rel_type
        RETURN from_node.id as from_id, from_node.attrs as from_attrs,
               to_node.id as to_id, to_node.attrs as to_attrs,
               rel_type
        LIMIT $limit
    """

    # =========================================================================
    # Dependency Queries
    # =========================================================================

    DEPENDENCIES_RECURSIVE_TEMPLATE = """
        MATCH (f1:File {repo_id: $repo_id})-[:IMPORTS]->(f2:File)
        WHERE f1 <> f2
        RETURN f1.id as from_id, f1.attrs as from_attrs,
               f2.id as to_id, f2.attrs as to_attrs
        LIMIT $limit
    """

    # =========================================================================
    # Full Repository Queries
    # =========================================================================

    FULL_REPO_SYMBOLS = """
        MATCH (s:Symbol {repo_id: $repo_id})
        RETURN s.id as id, s.attrs as attrs
        LIMIT $limit
    """

    FULL_REPO_EDGES_TEMPLATE = """
        MATCH (s1:Symbol {{repo_id: $repo_id}})-[r:{edge_types}]->(s2:Symbol)
        WHERE s1.id IN $node_ids AND s2.id IN $node_ids
        RETURN s1.id as from_id, s2.id as to_id, type(r) as rel_type
    """

    # =========================================================================
    # Comprehensive Graph Queries
    # =========================================================================

    COMPREHENSIVE_SYMBOLS = """
        MATCH (s:Symbol {repo_id: $repo_id})
        RETURN s.id as id, s.attrs as attrs
        LIMIT $node_limit
    """

    COMPREHENSIVE_EDGES_TEMPLATE = """
        MATCH path = (s1:Symbol {{repo_id: $repo_id}})-[:{rel_type}*1..{max_depth}]->(s2:Symbol)
        WITH s1, s2, relationships(path) as rels
        UNWIND rels as r
        WITH DISTINCT startNode(r).id as from_id, endNode(r).id as to_id
        RETURN from_id, to_id
        LIMIT 2000
    """

    # =========================================================================
    # Query Builders
    # =========================================================================

    @classmethod
    def build_calls_query(cls, max_depth: int, entry_point: Optional[str] = None, limit: int = 500) -> str:
        """Build a call chain query with dynamic depth and optional entry point.

        Args:
            max_depth: Maximum traversal depth.
            entry_point: Optional entry point pattern to start from.
            limit: Result limit.

        Returns:
            Formatted Cypher query string.
        """
        if entry_point:
            return cls.CALLS_FROM_ENTRY_POINT_TEMPLATE.format(max_depth=max_depth)
        else:
            return cls.CALLS_RECURSIVE_TEMPLATE.format(max_depth=max_depth)

    @classmethod
    def build_call_chain_query(cls, max_depth: int, direction: str = "outgoing") -> str:
        """Build a call chain query for a specific symbol.

        Args:
            max_depth: Maximum traversal depth.
            direction: "incoming" or "outgoing".

        Returns:
            Formatted Cypher query string.
        """
        if direction == "incoming":
            return cls.CALL_CHAIN_INCOMING_TEMPLATE.format(max_depth=max_depth)
        else:
            return cls.CALL_CHAIN_OUTGOING_TEMPLATE.format(max_depth=max_depth)

    @classmethod
    def build_hotspots_query(cls, min_connections: int = 5, limit: int = 20) -> str:
        """Build a hotspots query with dynamic parameters.

        Args:
            min_connections: Minimum connections to be considered a hotspot.
            limit: Maximum number of hotspots to return.

        Returns:
            Formatted Cypher query string.
        """
        return cls.HOTSPOTS_HIGH_DEGREE_TEMPLATE

    @classmethod
    def build_symbol_neighborhood_query(cls, max_depth: int = 2) -> str:
        """Build a symbol neighborhood query with dynamic depth.

        Args:
            max_depth: Maximum traversal depth.

        Returns:
            Formatted Cypher query string.
        """
        return cls.SYMBOL_NEIGHBORHOOD_TEMPLATE.format(max_depth=max_depth)

    @classmethod
    def build_dependencies_query(cls, max_depth: int = 3) -> str:
        """Build a dependencies query with dynamic depth.

        Args:
            max_depth: Maximum traversal depth for import chains.

        Returns:
            Formatted Cypher query string.
        """
        return cls.DEPENDENCIES_RECURSIVE_TEMPLATE

    @classmethod
    def build_full_repo_edges_query(cls, edge_types: list[str]) -> str:
        """Build a query for fetching edges of specific types.

        Args:
            edge_types: List of edge types to include.

        Returns:
            Formatted Cypher query string.
        """
        edge_pattern = "|".join(edge_types)
        return cls.FULL_REPO_EDGES_TEMPLATE.format(edge_types=edge_pattern)

    @classmethod
    def build_comprehensive_edges_query(cls, rel_type: str, max_depth: int = 15) -> str:
        """Build a query for fetching edges of a specific relationship type.

        Args:
            rel_type: Relationship type to query.
            max_depth: Maximum traversal depth.

        Returns:
            Formatted Cypher query string.
        """
        return cls.COMPREHENSIVE_EDGES_TEMPLATE.format(rel_type=rel_type, max_depth=max_depth)

    @classmethod
    def build_architecture_relationships_query(cls, rel_type: str, max_depth: int = 15) -> str:
        """Build a query for architecture relationships with dynamic depth.

        Args:
            rel_type: Relationship type to query.
            max_depth: Maximum traversal depth.

        Returns:
            Formatted Cypher query string.
        """
        return cls.ARCHITECTURE_RELATIONSHIPS_TEMPLATE.format(
            rel_type=rel_type,
            max_depth=max_depth
        )
