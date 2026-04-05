"""Cypher queries for graph statistics."""


# Node counts by label
NODE_COUNTS_QUERY = """
MATCH (n)
WHERE n.repo_id = $repo_id
RETURN labels(n)[0] as label, count(n) as count
ORDER BY count DESC
"""

# Symbol kind counts aggregated in Cypher via APOC JSON extraction
SYMBOL_KINDS_QUERY = """
MATCH (s:Symbol)
WHERE s.repo_id = $repo_id AND s.attrs IS NOT NULL
WITH apoc.convert.fromJsonMap(s.attrs).kind AS kind
WHERE kind IS NOT NULL
RETURN kind, count(*) as count
ORDER BY count DESC
"""

# Edge counts by relationship type
EDGE_COUNTS_QUERY = """
MATCH (n)-[r]->()
WHERE n.repo_id = $repo_id
RETURN type(r) as rel_type, count(r) as count
ORDER BY count DESC
"""

# Sample deep call chains
SAMPLE_CHAINS_QUERY = """
MATCH path = (s1:Symbol {repo_id: $repo_id})-[:CALLS*4..8]->(s2:Symbol)
WITH path, length(path) as depth
ORDER BY depth DESC
LIMIT $limit
RETURN
    nodes(path)[0].attrs as start_attrs,
    depth,
    nodes(path)[-1].attrs as end_attrs
"""

# Depth query templates (use .format(depth=N) to interpolate)
CALLS_DEPTH_TEMPLATE = (
    "MATCH (s1:Symbol)-[:CALLS*{depth}]->(s2:Symbol) WHERE s1.repo_id = $repo_id"
)
IMPORTS_DEPTH_TEMPLATE = (
    "MATCH (f1:File)-[:IMPORTS*{depth}]->(f2:File) WHERE f1.repo_id = $repo_id"
)
CONTAINS_DEPTH_TEMPLATE = (
    "MATCH (d:Directory)-[:CONTAINS*{depth}]->(f:File) WHERE d.repo_id = $repo_id"
)
EXTENDS_DEPTH_TEMPLATE = (
    "MATCH (s1:Symbol)-[:EXTENDS*{depth}]->(s2:Symbol) WHERE s1.repo_id = $repo_id"
)


class StatsQueries:
    """Cypher queries for statistics and metadata."""

    # Health check
    HEALTH_CHECK = "RETURN 1 as health"

    # Count symbols for a repo
    COUNT_SYMBOLS = "MATCH (s:Symbol {repo_id: $repo_id}) RETURN count(s) as cnt"

    # Count files for a repo
    COUNT_FILES = "MATCH (f:File {repo_id: $repo_id}) RETURN count(f) as cnt"

    # Count relationships for a repo
    COUNT_RELATIONSHIPS = """
        MATCH (n {repo_id: $repo_id})-[r]->()
        RETURN count(r) as cnt
    """

    # List files in a repo
    LIST_FILES = """
        MATCH (r:Repo {id: $repo_id})-[:CONTAINS]->(f:File)
        RETURN f.attrs as attrs
        ORDER BY f.id
    """

    # Get modules (top-level directories) for architecture overview
    GET_MODULES = """
        MATCH (r:Repo {id: $repo_id})-[:CONTAINS]->(f:File)
        WITH f.attrs AS attrs
        WHERE attrs IS NOT NULL
        RETURN attrs
    """

    # Get inter-file relationships for architecture overview
    @classmethod
    def get_relationships_query(cls) -> str:
        """
        Get inter-file relationships query.

        Note: This query uses dynamic edge type filtering. Pass edge_types parameter
        to filter by specific relationship types, or omit to get all relationships.
        """
        return """
            MATCH (r:Repo {id: $repo_id})-[:CONTAINS]->(f1:File)-[:CONTAINS]->(s1:Symbol)
            MATCH (s1)-[rel]->(s2:Symbol)<-[:CONTAINS]-(f2:File)
            WHERE f1 <> f2
              AND (size($edge_types) = 0 OR type(rel) IN $edge_types)
            RETURN DISTINCT type(rel) as rel_type,
                   f1.attrs as from_file,
                   f2.attrs as to_file
            LIMIT 100
        """
