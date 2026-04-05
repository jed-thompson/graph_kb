class SymbolQueries:
    """Cypher queries for symbol-specific operations.

    These queries support the V2 analysis adapters for entry point discovery,
    symbol filtering, and call chain traversal.

    All queries use COALESCE with APOC fallback for metadata extraction to support
    both migrated nodes (with top-level properties) and unmigrated nodes (with attrs JSON).
    """

    # Find symbols by kind (function, method, class, etc.)
    # Uses COALESCE with APOC fallback for unmigrated nodes
    # Note: {kind_conditions} is formatted at runtime based on the kinds list
    FIND_BY_KIND = """
        MATCH (s:Symbol {{repo_id: $repo_id}})
        WHERE {kind_conditions}
        RETURN s.id as id, s.attrs as attrs
    """

    # Find symbols by kind with folder path filtering
    # Uses COALESCE with APOC fallback for unmigrated nodes
    FIND_BY_KIND_WITH_PATH = """
        MATCH (s:Symbol {{repo_id: $repo_id}})
        WHERE ({kind_conditions})
          AND (s.file_path CONTAINS $folder_path
               OR s.attrs CONTAINS $folder_pattern)
        RETURN s.id as id, s.attrs as attrs
    """

    # Find entry points (functions and methods that could be API endpoints, CLI commands, etc.)
    # Uses CASE WHEN to avoid Neo4j warning about missing 'kind' property on unmigrated nodes
    FIND_ENTRY_POINTS = """
        MATCH (s:Symbol {repo_id: $repo_id})
        WHERE CASE WHEN s.kind IS NOT NULL THEN s.kind ELSE apoc.convert.fromJsonMap(s.attrs).kind END IN ['function', 'method']
        RETURN s.id as id, s.attrs as attrs
    """

    # Find entry points with folder path filtering
    # Uses CASE WHEN to avoid Neo4j warning about missing 'kind' property on unmigrated nodes
    FIND_ENTRY_POINTS_WITH_PATH = """
        MATCH (s:Symbol {repo_id: $repo_id})
        WHERE CASE WHEN s.kind IS NOT NULL THEN s.kind ELSE apoc.convert.fromJsonMap(s.attrs).kind END IN ['function', 'method']
          AND (s.file_path CONTAINS $folder_path
               OR s.attrs CONTAINS $folder_pattern)
        RETURN s.id as id, s.attrs as attrs
    """

    # Get symbols matching specified patterns (for SymbolQueryAdapter)
    GET_SYMBOLS_BY_PATTERN = """
        MATCH (s:Symbol {repo_id: $repo_id})
        WHERE s.attrs IS NOT NULL
        RETURN s.id as id, s.attrs as attrs
        LIMIT $limit
    """

    # Search for symbols by name (for SymbolQueryAdapter)
    SEARCH_BY_NAME = """
        MATCH (s:Symbol {repo_id: $repo_id})
        WHERE s.attrs CONTAINS $name_pattern1
           OR s.attrs CONTAINS $name_pattern2
        RETURN s.id as id, s.attrs as attrs
        LIMIT 20
    """

    # Traverse CALLS relationships for call chain analysis
    # Note: {max_depth} is formatted at runtime
    TRAVERSE_CALLS = """
        MATCH path = (start {{id: $start_id}})-[:CALLS*1..{max_depth}]->(end)
        WITH nodes(path) AS path_nodes, relationships(path) AS path_rels
        RETURN [n IN path_nodes | {{id: n.id, attrs: n.attrs}}] AS nodes,
               [r IN path_rels | {{
                   source: startNode(r).id,
                   target: endNode(r).id,
                   type: type(r)
               }}] AS relationships
    """

    # Traverse relationships with configurable types and direction
    # Note: {rel_pattern} is formatted at runtime
    TRAVERSE_RELATIONSHIPS = """
        MATCH path = (start {{id: $start_id}}){rel_pattern}(end)
        WITH nodes(path) AS path_nodes, relationships(path) AS path_rels
        RETURN [n IN path_nodes | {{id: n.id, attrs: n.attrs}}] AS nodes,
               [r IN path_rels | {{
                   source: startNode(r).id,
                   target: endNode(r).id,
                   type: type(r)
               }}] AS relationships
    """

    @classmethod
    def build_kind_conditions(cls, kinds: list[str]) -> str:
        """Build the WHERE conditions for filtering by symbol kinds.

        Uses COALESCE with APOC fallback to support both migrated nodes
        (with top-level 'kind' property) and unmigrated nodes (with attrs JSON).

        Args:
            kinds: List of symbol kinds to filter by (e.g., ["function", "method"]).

        Returns:
            String condition for the WHERE clause using COALESCE.
        """
        # Build a list of quoted kinds for the IN clause
        quoted_kinds = [f"'{kind}'" for kind in kinds]
        kinds_list = ", ".join(quoted_kinds)

        # Use CASE WHEN to avoid Neo4j warning about missing property
        return f"CASE WHEN s.kind IS NOT NULL THEN s.kind ELSE apoc.convert.fromJsonMap(s.attrs).kind END IN [{kinds_list}]"

    @classmethod
    def build_rel_pattern(
        cls,
        relationship_types: list[str],
        max_depth: int,
        direction: str = "outgoing",
    ) -> str:
        """Build the relationship pattern for traversal queries.

        Args:
            relationship_types: List of relationship types to traverse.
            max_depth: Maximum traversal depth (1-10).
            direction: "outgoing", "incoming", or "both".

        Returns:
            Relationship pattern string for Cypher query.
        """
        edge_pattern = "|".join(relationship_types)

        if direction == "outgoing":
            return f"-[r:{edge_pattern}*1..{max_depth}]->"
        elif direction == "incoming":
            return f"<-[r:{edge_pattern}*1..{max_depth}]-"
        else:
            return f"-[r:{edge_pattern}*1..{max_depth}]-"
