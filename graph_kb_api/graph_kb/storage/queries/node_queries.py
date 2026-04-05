
class NodeQueries:
    """Cypher queries for node CRUD operations."""

    # Create node with embedding
    # Note: {label} is formatted at runtime based on node type (Repo, File, Symbol, Chunk, Directory)
    CREATE_NODE_WITH_EMBEDDING = """
        MERGE (n:{label} {{id: $id}})
        SET n.repo_id = $repo_id,
            n.attrs = $attrs,
            n.summary = $summary,
            n.embedding = $embedding
    """

    # Create node without embedding
    CREATE_NODE = """
        MERGE (n:{label} {{id: $id}})
        SET n.repo_id = $repo_id,
            n.attrs = $attrs,
            n.summary = $summary
    """

    # Create chunk node with all properties
    CREATE_CHUNK_NODE = """
        MERGE (c:Chunk {id: $id})
        SET c.repo_id = $repo_id,
            c.file_path = $file_path,
            c.language = $language,
            c.start_line = $start_line,
            c.end_line = $end_line,
            c.content = $content,
            c.symbols_defined = $symbols_defined,
            c.symbols_referenced = $symbols_referenced,
            c.commit_sha = $commit_sha,
            c.chunk_type = $chunk_type,
            c.token_count = $token_count,
            c.embedding = $embedding
    """

    # Get node by ID
    GET_NODE_BY_ID = """
        MATCH (n {id: $id})
        RETURN n, labels(n) as labels
    """

    # Check if node exists
    NODE_EXISTS = "MATCH (n {id: $id}) RETURN count(n) > 0 as exists"

    # Delete node and its relationships
    DELETE_NODE = "MATCH (n {id: $id}) DETACH DELETE n"

    # Get chunks for a specific file
    GET_CHUNKS_FOR_FILE = """
        MATCH (c:Chunk {repo_id: $repo_id, file_path: $file_path})
        RETURN c as n, labels(c) as labels
        ORDER BY c.start_line
    """

    # Get chunks that define or reference a symbol
    GET_CHUNKS_FOR_SYMBOL = """
        MATCH (c:Chunk {repo_id: $repo_id})
        WHERE c.symbols_defined CONTAINS $symbol_name
           OR c.symbols_referenced CONTAINS $symbol_name
        RETURN c as n, labels(c) as labels
        ORDER BY c.file_path, c.start_line
    """

    # Get chunk with context (symbols and adjacent chunks)
    GET_CHUNK_WITH_CONTEXT = """
        MATCH (c:Chunk {id: $chunk_id})
        OPTIONAL MATCH (c)<-[:REPRESENTED_BY]-(s:Symbol)
        OPTIONAL MATCH (c)-[:NEXT_CHUNK]->(next:Chunk)
        OPTIONAL MATCH (prev:Chunk)-[:NEXT_CHUNK]->(c)
        RETURN collect(DISTINCT s) as symbols,
               collect(DISTINCT next) as next_chunks,
               collect(DISTINCT prev) as prev_chunks
    """
