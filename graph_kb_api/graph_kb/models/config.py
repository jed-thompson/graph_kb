"""Configuration dataclasses for Analysis V2 service."""

import json
from dataclasses import dataclass
from typing import Optional


@dataclass
class AnalysisConfig:
    """Configuration for Analysis V2 service.

    Attributes:
        neo4j_uri: URI for Neo4j database connection
        neo4j_user: Username for Neo4j authentication
        neo4j_password: Password for Neo4j authentication
        neo4j_database: Name of the Neo4j database
        embedding_model: Model name for embeddings
        llm_model: Optional LLM model name for narrative generation
        vector_index_name: Name of the vector index in Neo4j
        default_traversal_depth: Default depth for graph traversals
    """
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str = "neo4j"
    embedding_model: str = "all-MiniLM-L6-v2"
    llm_model: Optional[str] = None
    vector_index_name: str = "symbol_embeddings"
    default_traversal_depth: int = 5

    def to_json(self) -> str:
        """Serialize configuration to JSON.

        Returns:
            JSON string representation of the configuration.
        """
        return json.dumps({
            "neo4j_uri": self.neo4j_uri,
            "neo4j_user": self.neo4j_user,
            "neo4j_password": self.neo4j_password,
            "neo4j_database": self.neo4j_database,
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "vector_index_name": self.vector_index_name,
            "default_traversal_depth": self.default_traversal_depth,
        })

    @classmethod
    def from_json(cls, json_str: str) -> "AnalysisConfig":
        """Deserialize configuration from JSON.

        Args:
            json_str: JSON string to deserialize.

        Returns:
            AnalysisConfig instance.
        """
        data = json.loads(json_str)
        return cls(**data)


@dataclass
class RetrieverConfig:
    """Configuration for neo4j-graphrag retrievers.

    Attributes:
        index_name: Name of the vector index
        retrieval_query: Cypher query for retrieval expansion
        top_k: Number of top results to return
        score_threshold: Minimum similarity score threshold
    """
    index_name: str
    retrieval_query: str
    top_k: int = 10
    score_threshold: float = 0.7
