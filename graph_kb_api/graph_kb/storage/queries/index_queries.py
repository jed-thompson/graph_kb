class IndexQueries:
    """Cypher queries for index creation and management."""

    # Standard indexes for lookups
    CREATE_REPO_ID_INDEX = "CREATE INDEX repo_id_index IF NOT EXISTS FOR (n:Repo) ON (n.id)"
    CREATE_FILE_REPO_INDEX = "CREATE INDEX file_repo_index IF NOT EXISTS FOR (n:File) ON (n.repo_id)"
    CREATE_SYMBOL_REPO_INDEX = "CREATE INDEX symbol_repo_index IF NOT EXISTS FOR (n:Symbol) ON (n.repo_id)"
    CREATE_CHUNK_REPO_INDEX = "CREATE INDEX chunk_repo_index IF NOT EXISTS FOR (n:Chunk) ON (n.repo_id)"
    CREATE_NODE_ID_INDEX = "CREATE INDEX node_id_index IF NOT EXISTS FOR (n:Repo) ON (n.id)"
    CREATE_FILE_ID_INDEX = "CREATE INDEX file_id_index IF NOT EXISTS FOR (n:File) ON (n.id)"
    CREATE_SYMBOL_ID_INDEX = "CREATE INDEX symbol_id_index IF NOT EXISTS FOR (n:Symbol) ON (n.id)"
    CREATE_CHUNK_ID_INDEX = "CREATE INDEX chunk_id_index IF NOT EXISTS FOR (n:Chunk) ON (n.id)"
    CREATE_CHUNK_FILE_INDEX = "CREATE INDEX chunk_file_index IF NOT EXISTS FOR (n:Chunk) ON (n.file_path)"

    # Uniqueness constraints for data integrity
    CREATE_CHUNK_ID_UNIQUE = "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE"
    CREATE_FILE_ID_UNIQUE = "CREATE CONSTRAINT file_id_unique IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE"
    CREATE_SYMBOL_ID_UNIQUE = "CREATE CONSTRAINT symbol_id_unique IF NOT EXISTS FOR (s:Symbol) REQUIRE s.id IS UNIQUE"

    # Vector index creation template
    # Note: Uses string formatting for index_name, dimensions, similarity as these are
    # configuration values, not user input. The actual search queries use parameters.
    CREATE_VECTOR_INDEX = """
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (c:Chunk)
        ON c.embedding
        OPTIONS {{
            indexConfig: {{
                `vector.dimensions`: {dimensions},
                `vector.similarity_function`: '{similarity}'
            }}
        }}
    """

    @classmethod
    def get_standard_indexes(cls) -> list[str]:
        """Return list of all standard index creation queries."""
        return [
            cls.CREATE_REPO_ID_INDEX,
            cls.CREATE_FILE_REPO_INDEX,
            cls.CREATE_SYMBOL_REPO_INDEX,
            cls.CREATE_CHUNK_REPO_INDEX,
            cls.CREATE_NODE_ID_INDEX,
            cls.CREATE_FILE_ID_INDEX,
            cls.CREATE_SYMBOL_ID_INDEX,
            cls.CREATE_CHUNK_ID_INDEX,
            cls.CREATE_CHUNK_FILE_INDEX,
        ]

    @classmethod
    def get_uniqueness_constraints(cls) -> list[str]:
        """Return list of all uniqueness constraint queries."""
        return [
            cls.CREATE_CHUNK_ID_UNIQUE,
            cls.CREATE_FILE_ID_UNIQUE,
            cls.CREATE_SYMBOL_ID_UNIQUE,
        ]
