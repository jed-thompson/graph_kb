class VectorQueries:
    """Cypher queries for vector search operations."""

    # Vector similarity search
    # Note: {index_name} is formatted at runtime
    VECTOR_SEARCH = """
        CALL db.index.vector.queryNodes(
            '{index_name}',
            $top_k,
            $embedding
        ) YIELD node, score
        WHERE node.repo_id = $repo_id AND score >= $min_score
        RETURN node, score
        ORDER BY score DESC
    """

    # Vector search for code files only (excludes markdown)
    # Filters chunks where file_path does NOT end with '.md'
    # Limited to top_k results
    VECTOR_SEARCH_CODE_ONLY = """
        CALL db.index.vector.queryNodes(
            '{index_name}',
            $top_k,
            $embedding
        ) YIELD node, score
        WHERE node.repo_id = $repo_id
          AND score >= $min_score
          AND NOT node.file_path ENDS WITH '.md'
        RETURN node, score, false AS is_documentation
        ORDER BY score DESC
    """

    # Vector search for markdown files only (documentation)
    # Filters chunks where file_path ends with '.md'
    # Uses high limit (100) instead of top_k to get all relevant markdown
    VECTOR_SEARCH_MARKDOWN_ONLY = """
        CALL db.index.vector.queryNodes(
            '{index_name}',
            $markdown_limit,
            $embedding
        ) YIELD node, score
        WHERE node.repo_id = $repo_id
          AND score >= $min_score
          AND node.file_path ENDS WITH '.md'
        RETURN node, score, true AS is_documentation
        ORDER BY score DESC
    """


class TraversalQueries:
    """Cypher queries for graph traversal operations.

    Used by neo4j-graphrag retrievers for vector/hybrid search with graph expansion.
    """

    # Unified RAG query that combines vector search with graph context expansion
    # in a single Cypher statement. Includes file context, symbol context, and
    # related symbols via CALLS/IMPORTS/USES relationships.
    # Uses COALESCE with APOC fallback for metadata extraction from attrs JSON.
    UNIFIED_RAG_QUERY = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $question_embedding)
    YIELD node AS chunk, score
    WHERE chunk.repo_id = $repo_id AND score >= $min_score

    MATCH (file:File)-[:CONTAINS]->(chunk)
    OPTIONAL MATCH (symbol:Symbol)-[:REPRESENTED_BY]->(chunk)
    OPTIONAL MATCH (symbol)-[r:CALLS|IMPORTS|USES]->(related:Symbol)

    WITH chunk, score, file, symbol,
         collect(DISTINCT CASE WHEN related IS NOT NULL THEN {
             name: COALESCE(related.name, apoc.convert.fromJsonMap(related.attrs).name),
             kind: COALESCE(related.kind, apoc.convert.fromJsonMap(related.attrs).kind),
             relationship: type(r)
         } ELSE NULL END) AS related_raw

    RETURN
        chunk.id AS chunk_id,
        chunk.content AS chunk_content,
        chunk.start_line AS start_line,
        chunk.end_line AS end_line,
        score AS similarity_score,
        COALESCE(file.file_path, apoc.convert.fromJsonMap(file.attrs).path, file.id) AS file_path,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.name, apoc.convert.fromJsonMap(symbol.attrs).name)
             ELSE NULL END AS symbol_name,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.kind, apoc.convert.fromJsonMap(symbol.attrs).kind)
             ELSE NULL END AS symbol_kind,
        [x IN related_raw WHERE x IS NOT NULL] AS related_symbols
    ORDER BY score DESC
    """

    # Unified RAG query variant without related symbols expansion
    # For use when include_related_symbols=False to improve performance
    UNIFIED_RAG_QUERY_NO_RELATED = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $question_embedding)
    YIELD node AS chunk, score
    WHERE chunk.repo_id = $repo_id AND score >= $min_score

    MATCH (file:File)-[:CONTAINS]->(chunk)
    OPTIONAL MATCH (symbol:Symbol)-[:REPRESENTED_BY]->(chunk)

    RETURN
        chunk.id AS chunk_id,
        chunk.content AS chunk_content,
        chunk.start_line AS start_line,
        chunk.end_line AS end_line,
        score AS similarity_score,
        COALESCE(file.file_path, apoc.convert.fromJsonMap(file.attrs).path, file.id) AS file_path,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.name, apoc.convert.fromJsonMap(symbol.attrs).name)
             ELSE NULL END AS symbol_name,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.kind, apoc.convert.fromJsonMap(symbol.attrs).kind)
             ELSE NULL END AS symbol_kind,
        [] AS related_symbols
    ORDER BY score DESC
    """

    # Unified RAG query for code files only (excludes markdown)
    # Filters chunks where file_path does NOT end with '.md'
    # Limited to top_k results
    UNIFIED_RAG_QUERY_CODE_ONLY = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $question_embedding)
    YIELD node AS chunk, score
    WHERE chunk.repo_id = $repo_id
      AND score >= $min_score
      AND NOT chunk.file_path ENDS WITH '.md'

    MATCH (file:File)-[:CONTAINS]->(chunk)
    OPTIONAL MATCH (symbol:Symbol)-[:REPRESENTED_BY]->(chunk)
    OPTIONAL MATCH (symbol)-[r:CALLS|IMPORTS|USES]->(related:Symbol)

    WITH chunk, score, file, symbol,
         collect(DISTINCT CASE WHEN related IS NOT NULL THEN {
             name: COALESCE(related.name, apoc.convert.fromJsonMap(related.attrs).name),
             kind: COALESCE(related.kind, apoc.convert.fromJsonMap(related.attrs).kind),
             relationship: type(r)
         } ELSE NULL END) AS related_raw

    RETURN
        chunk.id AS chunk_id,
        chunk.content AS chunk_content,
        chunk.start_line AS start_line,
        chunk.end_line AS end_line,
        score AS similarity_score,
        COALESCE(file.file_path, apoc.convert.fromJsonMap(file.attrs).path, file.id) AS file_path,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.name, apoc.convert.fromJsonMap(symbol.attrs).name)
             ELSE NULL END AS symbol_name,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.kind, apoc.convert.fromJsonMap(symbol.attrs).kind)
             ELSE NULL END AS symbol_kind,
        [x IN related_raw WHERE x IS NOT NULL] AS related_symbols,
        false AS is_documentation
    ORDER BY score DESC
    """

    # Unified RAG query for code files only without related symbols
    UNIFIED_RAG_QUERY_CODE_ONLY_NO_RELATED = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $question_embedding)
    YIELD node AS chunk, score
    WHERE chunk.repo_id = $repo_id
      AND score >= $min_score
      AND NOT chunk.file_path ENDS WITH '.md'

    MATCH (file:File)-[:CONTAINS]->(chunk)
    OPTIONAL MATCH (symbol:Symbol)-[:REPRESENTED_BY]->(chunk)

    RETURN
        chunk.id AS chunk_id,
        chunk.content AS chunk_content,
        chunk.start_line AS start_line,
        chunk.end_line AS end_line,
        score AS similarity_score,
        COALESCE(file.file_path, apoc.convert.fromJsonMap(file.attrs).path, file.id) AS file_path,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.name, apoc.convert.fromJsonMap(symbol.attrs).name)
             ELSE NULL END AS symbol_name,
        CASE WHEN symbol IS NOT NULL
             THEN COALESCE(symbol.kind, apoc.convert.fromJsonMap(symbol.attrs).kind)
             ELSE NULL END AS symbol_kind,
        [] AS related_symbols,
        false AS is_documentation
    ORDER BY score DESC
    """

    # Unified RAG query for markdown files only (documentation)
    # Filters chunks where file_path ends with '.md'
    # Uses high limit instead of top_k to get all relevant markdown
    UNIFIED_RAG_QUERY_MARKDOWN_ONLY = """
    CALL db.index.vector.queryNodes($index_name, $markdown_limit, $question_embedding)
    YIELD node AS chunk, score
    WHERE chunk.repo_id = $repo_id
      AND score >= $min_score
      AND chunk.file_path ENDS WITH '.md'

    MATCH (file:File)-[:CONTAINS]->(chunk)

    RETURN
        chunk.id AS chunk_id,
        chunk.content AS chunk_content,
        chunk.start_line AS start_line,
        chunk.end_line AS end_line,
        score AS similarity_score,
        COALESCE(file.file_path, apoc.convert.fromJsonMap(file.attrs).path, file.id) AS file_path,
        NULL AS symbol_name,
        NULL AS symbol_kind,
        [] AS related_symbols,
        true AS is_documentation
    ORDER BY score DESC
    """

    # Vector search with 2-hop neighbor expansion (hop1 and hop2 separately)
    # Uses id property matching instead of elementId() for stable identification
    # Uses COALESCE with APOC fallback for metadata extraction from attrs JSON
    VECTOR_CYPHER_RETRIEVAL = """
    MATCH (node {id: $node_id})

    OPTIONAL MATCH (node)-[r1]-(neighbor1)
    WHERE neighbor1.repo_id = $repo_id OR $repo_id IS NULL

    OPTIONAL MATCH (neighbor1)-[r2]-(neighbor2)
    WHERE (neighbor2.repo_id = $repo_id OR $repo_id IS NULL)
    AND neighbor2 <> node

    WITH node,
         collect(DISTINCT {
             id: neighbor1.id,
             name: COALESCE(neighbor1.name, apoc.convert.fromJsonMap(neighbor1.attrs).name),
             kind: COALESCE(neighbor1.kind, apoc.convert.fromJsonMap(neighbor1.attrs).kind),
             type: labels(neighbor1)[0],
             rel_type: type(r1)
         }) AS hop1_neighbors,
         collect(DISTINCT {
             id: neighbor2.id,
             name: COALESCE(neighbor2.name, apoc.convert.fromJsonMap(neighbor2.attrs).name),
             kind: COALESCE(neighbor2.kind, apoc.convert.fromJsonMap(neighbor2.attrs).kind),
             type: labels(neighbor2)[0],
             rel_type: type(r2)
         }) AS hop2_neighbors

    RETURN node.id AS node_id,
           COALESCE(node.name, apoc.convert.fromJsonMap(node.attrs).name) AS name,
           COALESCE(node.kind, apoc.convert.fromJsonMap(node.attrs).kind) AS kind,
           COALESCE(node.file_path, apoc.convert.fromJsonMap(node.attrs).file_path) AS file_path,
           node.content AS content,
           node.summary AS summary,
           COALESCE(node.docstring, apoc.convert.fromJsonMap(node.attrs).docstring) AS docstring,
           node.start_line AS start_line,
           node.end_line AS end_line,
           labels(node)[0] AS node_type,
           hop1_neighbors,
           hop2_neighbors
    """

    # Hybrid search with path-based neighbor expansion (includes distance)
    # Uses id property matching instead of elementId() for stable identification
    # Uses COALESCE with APOC fallback for metadata extraction from attrs JSON
    HYBRID_CYPHER_RETRIEVAL = """
    MATCH (node {id: $node_id})

    OPTIONAL MATCH path = (node)-[*1..2]-(related)
    WHERE related.repo_id = $repo_id OR $repo_id IS NULL

    WITH node,
         collect(DISTINCT {
             id: related.id,
             name: COALESCE(related.name, apoc.convert.fromJsonMap(related.attrs).name),
             kind: COALESCE(related.kind, apoc.convert.fromJsonMap(related.attrs).kind),
             type: labels(related)[0],
             distance: length(path)
         }) AS related_nodes

    RETURN node.id AS node_id,
           COALESCE(node.name, apoc.convert.fromJsonMap(node.attrs).name) AS name,
           COALESCE(node.kind, apoc.convert.fromJsonMap(node.attrs).kind) AS kind,
           COALESCE(node.file_path, apoc.convert.fromJsonMap(node.attrs).file_path) AS file_path,
           node.content AS content,
           node.summary AS summary,
           COALESCE(node.docstring, apoc.convert.fromJsonMap(node.attrs).docstring) AS docstring,
           node.start_line AS start_line,
           node.end_line AS end_line,
           labels(node)[0] AS node_type,
           related_nodes
    """

    @classmethod
    def build_traversal_query(cls, depth: int, relationship_types: list[str]) -> str:
        """Build Cypher query for graph traversal with specified depth.

        Uses id property matching instead of elementId() for stable identification.
        Uses COALESCE with APOC fallback for metadata extraction from attrs JSON.

        Args:
            depth: Maximum traversal depth (1-3 recommended).
            relationship_types: List of relationship types to traverse.

        Returns:
            Cypher query string for graph traversal.
        """
        rel_filter = "|".join(relationship_types)

        return f"""
        MATCH (node {{id: $node_id}})

        OPTIONAL MATCH path = (node)-[:{rel_filter}*1..{depth}]-(related)
        WHERE (related.repo_id = $repo_id OR $repo_id IS NULL)
        AND related <> node

        WITH node,
             collect(DISTINCT {{
                 id: related.id,
                 name: COALESCE(related.name, apoc.convert.fromJsonMap(related.attrs).name),
                 kind: COALESCE(related.kind, apoc.convert.fromJsonMap(related.attrs).kind),
                 type: labels(related)[0],
                 file_path: COALESCE(related.file_path, apoc.convert.fromJsonMap(related.attrs).file_path),
                 distance: length(path),
                 path_rels: [r IN relationships(path) | type(r)]
             }}) AS traversed_nodes

        RETURN node.id AS node_id,
               COALESCE(node.name, apoc.convert.fromJsonMap(node.attrs).name) AS name,
               COALESCE(node.kind, apoc.convert.fromJsonMap(node.attrs).kind) AS kind,
               COALESCE(node.file_path, apoc.convert.fromJsonMap(node.attrs).file_path) AS file_path,
               node.content AS content,
               node.summary AS summary,
               COALESCE(node.docstring, apoc.convert.fromJsonMap(node.attrs).docstring) AS docstring,
               node.start_line AS start_line,
               node.end_line AS end_line,
               labels(node)[0] AS node_type,
               traversed_nodes,
               size(traversed_nodes) AS traversal_count
        """

    # Symbol expansion query - broader search using symbol name
    # Used when specific patterns don't match
    SYMBOL_EXPANSION_BROADER = """
    MATCH (s:Symbol {repo_id: $repo_id})
    WHERE s.name = $symbol_name OR s.name CONTAINS $symbol_name
    MATCH (s)-[:{edge_pattern}*1..{hops}]-(related:Symbol)
    MATCH (related)<-[:CONTAINS]-(f:File)-[:CONTAINS]->(c:Chunk)
    WHERE c.repo_id = $repo_id AND NOT c.id IN $exclude_ids
    RETURN DISTINCT c as node, labels(c) as labels
    LIMIT $limit
    """

    @classmethod
    def build_symbol_expansion_query(cls, edge_pattern: str, hops: int) -> str:
        """Build symbol expansion query with specified edge pattern and hops.

        Args:
            edge_pattern: Edge pattern like "CALLS|IMPORTS|USES"
            hops: Number of hops to traverse (1-3 recommended)

        Returns:
            Cypher query string for symbol expansion
        """
        return f"""
        MATCH (s:Symbol {{repo_id: $repo_id}})
        WHERE s.name = $symbol_name OR s.name CONTAINS $symbol_name
        MATCH (s)-[:{edge_pattern}*1..{hops}]-(related:Symbol)
        MATCH (related)<-[:CONTAINS]-(f:File)-[:CONTAINS]->(c:Chunk)
        WHERE c.repo_id = $repo_id AND NOT c.id IN $exclude_ids
        RETURN DISTINCT c as node, labels(c) as labels
        LIMIT $limit
        """
