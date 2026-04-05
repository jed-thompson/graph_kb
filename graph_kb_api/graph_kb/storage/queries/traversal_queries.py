"""Cypher queries for graph traversal operations.

These queries support the TraversalAdapter for multi-hop graph traversal,
neighborhood expansion, and reachability analysis.
"""


class TraversalQueries:
    """Cypher queries for graph traversal operations."""

    # Iterative traversal query - fetches neighbors one depth level at a time
    # This prevents memory explosion on large graphs by limiting results per iteration
    ITERATIVE_NEIGHBORS = """
        UNWIND $frontier_ids AS fid
        MATCH (start {{id: fid}}){rel_pattern}(neighbor)
        WHERE NOT neighbor.id IN $seen_ids
        WITH DISTINCT neighbor,
             startNode(r).id AS source_id,
             endNode(r).id AS target_id,
             type(r) AS rel_type
        RETURN neighbor AS n, labels(neighbor) AS labels,
               source_id, target_id, rel_type
        LIMIT 1000
    """

    @classmethod
    def build_rel_pattern(
        cls,
        edge_types: list[str],
        direction: str = "outgoing",
    ) -> str:
        """Build the relationship pattern for traversal queries.

        Args:
            edge_types: List of edge types to traverse (e.g., ["CALLS", "IMPORTS"]).
            direction: "outgoing", "incoming", or "both".

        Returns:
            Relationship pattern string for Cypher query.
        """
        edge_pattern = "|".join(edge_types)

        if direction == "outgoing":
            return f"-[r:{edge_pattern}]->"
        elif direction == "incoming":
            return f"<-[r:{edge_pattern}]-"
        else:  # both
            return f"-[r:{edge_pattern}]-"
