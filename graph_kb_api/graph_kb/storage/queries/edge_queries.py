from typing import List, Optional

from ...models.enums import GraphEdgeType


class EdgeQueries:
    """Cypher queries for edge/relationship operations."""

    # Create edge between nodes
    # Note: {edge_type} is formatted at runtime based on edge type
    CREATE_EDGE = """
        MATCH (a {{id: $from_id}})
        MATCH (b {{id: $to_id}})
        MERGE (a)-[r:{edge_type} {{id: $edge_id}}]->(b)
        SET r.attrs = $attrs
    """

    # Check if edge exists
    # Note: {edge_type} is formatted at runtime
    EDGE_EXISTS = """
        MATCH (a {{id: $from_id}})-[r:{edge_type}]->(b {{id: $to_id}})
        RETURN count(r) > 0 as exists
    """

    # Get outgoing neighbors
    # Note: {edge_pattern} is formatted at runtime (e.g., "CALLS|IMPORTS")
    GET_NEIGHBORS_OUTGOING = """
        MATCH (source {{id: $id}})-[r:{edge_pattern}]->(n)
        RETURN n, labels(n) as labels
        LIMIT $limit
    """

    # Get incoming neighbors
    GET_NEIGHBORS_INCOMING = """
        MATCH (source {{id: $id}})<-[r:{edge_pattern}]-(n)
        RETURN n, labels(n) as labels
        LIMIT $limit
    """

    # Get neighbors in both directions
    GET_NEIGHBORS_BOTH = """
        MATCH (source {{id: $id}})-[r:{edge_pattern}]-(n)
        RETURN DISTINCT n, labels(n) as labels
        LIMIT $limit
    """

    # Get reachable nodes with path information
    # Note: {rel_pattern} is formatted at runtime (e.g., "-[r:CALLS|IMPORTS*1..5]->")
    GET_REACHABLE_NODES = """
        MATCH path = (start {{id: $start_id}}){rel_pattern}(end)
        WITH nodes(path) AS path_nodes, relationships(path) AS path_rels
        UNWIND path_nodes AS n
        WITH DISTINCT n, path_rels
        RETURN n, labels(n) AS labels,
               [rel IN path_rels | {{
                   source: startNode(rel).id,
                   target: endNode(rel).id,
                   type: type(rel)
               }}] AS edges
    """

    # Find shortest path with specific edge types
    # Note: {edge_pattern} and {max_hops} are formatted at runtime
    FIND_PATH_WITH_TYPES = """
        MATCH p = shortestPath((a {{id: $from_id}})-[:{edge_pattern}*1..{max_hops}]-(b {{id: $to_id}}))
        RETURN [n IN nodes(p) | n.id] AS path
    """

    # Find shortest path with any edge type
    FIND_PATH_ANY_TYPE = """
        MATCH p = shortestPath((a {{id: $from_id}})-[*1..{max_hops}]-(b {{id: $to_id}}))
        RETURN [n IN nodes(p) | n.id] AS path
    """

    # Get available edge types for a repository
    GET_AVAILABLE_EDGE_TYPES = """
        MATCH (a)-[r]->(b)
        WHERE (a.repo_id = $repo_id OR b.repo_id = $repo_id)
        RETURN DISTINCT type(r) as rel_type
    """

    # Expand from symbol to find related chunks
    @classmethod
    def get_expand_from_symbol_query(cls, hops: int = 3, edge_types: Optional[List[str]] = None) -> str:
        """Build the EXPAND_FROM_SYMBOL query with specified edge types.

        Args:
            hops: Number of relationship hops to traverse (default 3).
            edge_types: List of edge types to use. If None, uses all semantic edges.

        Returns:
            Cypher query string with hops baked in.
        """
        if edge_types is None:
            edge_types = GraphEdgeType.semantic_edges()

        rel_pattern = "|".join(edge_types)
        return f"""
            MATCH (s:Symbol {{repo_id: $repo_id}})
            WHERE s.attrs CONTAINS $symbol_pattern
            MATCH (s)-[:{rel_pattern}*1..{hops}]-(related:Symbol)
            MATCH (related)<-[:CONTAINS]-(f:File)-[:CONTAINS]->(c:Chunk)
            WHERE c.repo_id = $repo_id AND NOT c.id IN $exclude_ids
            RETURN DISTINCT c as node, labels(c) as labels
            LIMIT $limit
        """
