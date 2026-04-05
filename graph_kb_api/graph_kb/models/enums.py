"""Enum types for the graph knowledge base."""

from enum import Enum


class RepoStatus(str, Enum):
    """Repository indexing status."""

    PENDING = "pending"
    INDEXING = "indexing"
    PAUSED = "paused"  # Indexing was paused, can be resumed
    READY = "ready"
    ERROR = "error"


class DocumentStatus(str, Enum):
    """Document ingestion status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class SymbolKind(str, Enum):
    """Types of code symbols that can be extracted."""

    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    MODULE = "module"
    VARIABLE = "variable"
    CONSTANT = "constant"
    TYPE_ALIAS = "type_alias"
    PROPERTY = "property"
    PARAMETER = "parameter"
    DECORATOR = "decorator"


class Visibility(str, Enum):
    """Symbol visibility/access modifiers."""

    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    INTERNAL = "internal"


class RelationshipType(str, Enum):
    """Types of relationships between symbols."""

    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    IMPLEMENTS = "IMPLEMENTS"
    EXTENDS = "EXTENDS"
    USES = "USES"  # Variable/constant references
    DECORATES = "DECORATES"  # Decorator applied to symbol
    RETURNS = "RETURNS"  # Function returns type
    ACCEPTS = "ACCEPTS"  # Function accepts parameter type


class GraphNodeType(str, Enum):
    """Types of nodes in the code graph."""

    REPO = "Repo"
    DIRECTORY = "Directory"
    FILE = "File"
    SYMBOL = "Symbol"
    CHUNK = "Chunk"  # New: Code chunks as first-class nodes


class GraphEdgeType(str, Enum):
    """Types of edges in the code graph."""

    CONTAINS = "CONTAINS"
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    IMPLEMENTS = "IMPLEMENTS"
    EXTENDS = "EXTENDS"
    REPRESENTED_BY = "REPRESENTED_BY"  # Symbol -> Chunk (structural metadata)
    USES = "USES"  # Symbol uses another symbol (variable reference)
    DECORATES = "DECORATES"  # Decorator -> Symbol
    NEXT_CHUNK = "NEXT_CHUNK"  # Sequential chunk ordering (structural metadata)

    @classmethod
    def semantic_edges(cls) -> list[str]:
        """Get all semantic edge types (excludes structural metadata edges).

        Semantic edges represent meaningful code relationships like calls, imports,
        inheritance, etc. Structural edges like REPRESENTED_BY and NEXT_CHUNK are
        excluded as they're internal graph structure.

        Returns:
            List of semantic edge type values for graph traversal.

        Note:
            Only includes edge types that are actually extracted by parsers:
            - CALLS, IMPORTS, EXTENDS, DECORATES: Extracted for all languages
            - IMPLEMENTS: Extracted for TypeScript/JavaScript only
            - CONTAINS: Structural containment (Repo→Dir→File→Symbol)

            Not included (not yet implemented in parsers):
            - USES: Variable/constant references (TODO)

            For Python-only repositories, IMPLEMENTS warnings are harmless since
            Python doesn't have interfaces.
        """
        return [
            cls.CALLS.value,
            cls.IMPORTS.value,
            cls.EXTENDS.value,
            cls.IMPLEMENTS.value,
            cls.CONTAINS.value,
            cls.DECORATES.value,
            cls.USES.value,
        ]




class ContextItemType(str, Enum):
    """Types of context items in retrieval response."""

    CHUNK = "chunk"
    GRAPH_PATH = "graph_path"
    DIRECTORY_SUMMARY = "directory_summary"


class Language(str, Enum):
    """Supported programming languages."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    GO = "go"
    JAVA = "java"
    RUBY = "ruby"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    MARKDOWN = "markdown"
    YAML = "yaml"
    JSON = "json"
    UNKNOWN = "unknown"


class DeletionPhase(str, Enum):
    """Phases of the repository deletion process."""

    INITIALIZING = "initializing"
    DELETING_CHROMA = "deleting_chroma"
    DELETING_NEO4J_CHUNKS = "deleting_neo4j_chunks"
    DELETING_NEO4J_SYMBOLS = "deleting_neo4j_symbols"
    DELETING_NEO4J_FILES = "deleting_neo4j_files"
    DELETING_NEO4J_DIRECTORIES = "deleting_neo4j_directories"
    DELETING_NEO4J_REPO = "deleting_neo4j_repo"
    COMPLETED = "completed"
    ERROR = "error"


class IndexingPhase(str, Enum):
    """Phases of the repository indexing process."""

    INITIALIZING = "initializing"
    DISCOVERING_FILES = "discovering_files"
    INDEXING_FILES = "indexing_files"
    RESOLVING_RELATIONSHIPS = "resolving_relationships"  # Pass 2: cross-file edge creation
    GENERATING_EMBEDDINGS = "generating_embeddings"
    BUILDING_GRAPH = "building_graph"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    PAUSED = "paused"  # Indexing was paused by user
    ERROR = "error"


class FileStatus(str, Enum):
    """File indexing status for checkpoint tracking."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
