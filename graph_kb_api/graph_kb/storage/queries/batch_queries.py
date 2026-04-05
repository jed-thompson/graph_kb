class BatchQueries:
    """Cypher queries for bulk/batch operations."""

    # Count chunks for a file
    COUNT_CHUNKS_FOR_FILE = """
        MATCH (c:Chunk {repo_id: $repo_id, file_path: $file_path})
        RETURN count(c) as cnt
    """

    # Delete chunks for a file in batches
    DELETE_CHUNKS_FOR_FILE_BATCH = """
        CALL {
            MATCH (c:Chunk {repo_id: $repo_id, file_path: $file_path})
            WITH c LIMIT 1000
            DETACH DELETE c
            RETURN count(*) as deleted
        } IN TRANSACTIONS OF 1000 ROWS
        RETURN sum(deleted) as total
    """

    # Count symbols for a file
    COUNT_SYMBOLS_FOR_FILE = """
        MATCH (f:File {repo_id: $repo_id})
        WHERE f.attrs CONTAINS $file_path_pattern
        MATCH (f)-[:CONTAINS]->(s:Symbol)
        RETURN count(s) as cnt
    """

    # Delete symbols for a file in batches
    DELETE_SYMBOLS_FOR_FILE_BATCH = """
        CALL {
            MATCH (f:File {repo_id: $repo_id})
            WHERE f.attrs CONTAINS $file_path_pattern
            MATCH (f)-[:CONTAINS]->(s:Symbol)
            WITH s LIMIT 1000
            DETACH DELETE s
            RETURN count(*) as deleted
        } IN TRANSACTIONS OF 1000 ROWS
        RETURN sum(deleted) as total
    """

    # Delete file node
    DELETE_FILE_NODE = """
        MATCH (f:File {repo_id: $repo_id})
        WHERE f.attrs CONTAINS $file_path_pattern
        WITH f, count(f) as cnt
        DETACH DELETE f
        RETURN cnt
    """

    # Count nodes by type for a repo
    COUNT_CHUNKS_FOR_REPO = "MATCH (c:Chunk {repo_id: $repo_id}) RETURN count(c) as cnt"
    COUNT_SYMBOLS_FOR_REPO = "MATCH (s:Symbol {repo_id: $repo_id}) RETURN count(s) as cnt"
    COUNT_FILES_FOR_REPO = "MATCH (f:File {repo_id: $repo_id}) RETURN count(f) as cnt"
    COUNT_DIRECTORIES_FOR_REPO = "MATCH (d:Directory {repo_id: $repo_id}) RETURN count(d) as cnt"

    # Delete nodes by type for a repo in batches
    DELETE_CHUNKS_FOR_REPO_BATCH = """
        CALL {
            MATCH (c:Chunk {repo_id: $repo_id})
            WITH c LIMIT 1000
            DETACH DELETE c
            RETURN count(*) as deleted
        } IN TRANSACTIONS OF 1000 ROWS
        RETURN sum(deleted) as total
    """

    DELETE_SYMBOLS_FOR_REPO_BATCH = """
        CALL {
            MATCH (s:Symbol {repo_id: $repo_id})
            WITH s LIMIT 1000
            DETACH DELETE s
            RETURN count(*) as deleted
        } IN TRANSACTIONS OF 1000 ROWS
        RETURN sum(deleted) as total
    """

    DELETE_FILES_FOR_REPO_BATCH = """
        CALL {
            MATCH (f:File {repo_id: $repo_id})
            WITH f LIMIT 1000
            DETACH DELETE f
            RETURN count(*) as deleted
        } IN TRANSACTIONS OF 1000 ROWS
        RETURN sum(deleted) as total
    """

    DELETE_DIRECTORIES_FOR_REPO_BATCH = """
        CALL {
            MATCH (d:Directory {repo_id: $repo_id})
            WITH d LIMIT 1000
            DETACH DELETE d
            RETURN count(*) as deleted
        } IN TRANSACTIONS OF 1000 ROWS
        RETURN sum(deleted) as total
    """

    # Delete repo node
    DELETE_REPO_NODE = """
        MATCH (r:Repo {id: $repo_id})
        WITH r, count(r) as cnt
        DETACH DELETE r
        RETURN cnt
    """

    # Batch upsert chunks with embeddings
    # Note: {set_clause} is formatted at runtime based on store_content/store_embedding flags
    UPSERT_CHUNKS_BATCH = """
        CALL {{
            WITH $rows AS rows, $file_node_id AS file_node_id
            UNWIND rows AS row
            MERGE (c:Chunk {{id: row.id}})
            SET {set_clause}
            WITH c, row, file_node_id
            MATCH (f:File {{id: file_node_id}})
            MERGE (f)-[:CONTAINS]->(c)
        }} IN TRANSACTIONS OF 1000 ROWS
    """

    # Batch upsert symbol-chunk links
    UPSERT_SYMBOL_CHUNK_LINKS_BATCH = """
        CALL {
            WITH $links AS links
            UNWIND links AS link
            MATCH (s:Symbol {id: link.symbol_id})
            MATCH (c:Chunk {id: link.chunk_id})
            MERGE (s)-[:REPRESENTED_BY]->(c)
        } IN TRANSACTIONS OF 1000 ROWS
    """

    # Batch upsert next chunk edges
    UPSERT_NEXT_CHUNK_EDGES_BATCH = """
        CALL {
            WITH $edges AS edges
            UNWIND edges AS edge
            MATCH (c1:Chunk {id: edge.from_chunk_id})
            MATCH (c2:Chunk {id: edge.to_chunk_id})
            MERGE (c1)-[:NEXT_CHUNK]->(c2)
        } IN TRANSACTIONS OF 1000 ROWS
    """

    @classmethod
    def build_upsert_chunks_set_clause(
        cls,
        store_content: bool = True,
        store_embedding: bool = True,
    ) -> str:
        """Build the SET clause for chunk upsert based on configuration.

        Args:
            store_content: Whether to include content property.
            store_embedding: Whether to include embedding property.

        Returns:
            Comma-separated SET clause string.
        """
        set_clauses = [
            "c.repo_id = row.repo_id",
            "c.chunk_id = row.chunk_id",
            "c.file_path = row.file_path",
            "c.language = row.language",
            "c.start_line = row.start_line",
            "c.end_line = row.end_line",
            "c.commit_sha = row.commit_sha",
            "c.chunk_type = row.chunk_type",
            "c.token_count = row.token_count",
            "c.symbols_defined = row.symbols_defined",
            "c.symbols_referenced = row.symbols_referenced",
            "c.ts_indexed = row.ts_indexed",
        ]

        if store_content:
            set_clauses.append("c.content = row.content")

        if store_embedding:
            set_clauses.append("c.embedding = row.embedding")

        return ", ".join(set_clauses)
