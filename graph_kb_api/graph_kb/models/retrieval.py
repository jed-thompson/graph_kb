"""Data models for retrieval operations."""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class RetrievalStep(str, Enum):
    """Enumeration of retrieval pipeline steps for progress tracking."""

    VECTOR_SEARCH = "Vector search"
    ANCHOR_EXPANSION = "Anchor expansion"
    GRAPH_EXPANSION = "Graph expansion"
    LOCATION_SCORING = "Location scoring"
    RANKING_RESULTS = "Ranking results"
    BUILDING_CONTEXT = "Building context"
    DOMAIN_RETRIEVAL = "Domain retrieval"


@dataclass
class SymbolMatch:
    """A symbol matching a search pattern."""

    id: str
    name: str
    kind: str
    file_path: str
    docstring: Optional[str] = None


@dataclass
class CandidateChunk:
    """A candidate chunk for retrieval with scoring information."""

    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    symbol: Optional[str]
    vector_score: float
    graph_distance: int = -1  # -1 means not connected via graph
    is_anchor: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def final_score(self) -> float:
        """Calculate final score combining all factors."""
        score = self.vector_score

        # Graph distance bonus (closer = better)
        if self.graph_distance >= 0:
            graph_bonus = 0.3 / (self.graph_distance + 1)
            score += graph_bonus

        # Anchor bonus
        if self.is_anchor:
            score += 0.2

        return score


def _get_default_retrieval_values():
    """Get default retrieval values from settings.

    Returns a dict of default values. Falls back to hardcoded values
    if settings can't be loaded (e.g., during initial import).
    """
    try:
        from graph_kb_api.config import settings

        if hasattr(settings, "retrieval_defaults"):
            defaults = settings.retrieval_defaults
            return {
                "max_context_tokens": defaults.max_context_tokens,
                "top_k_vector": defaults.top_k_vector,
                "graph_expansion_hops": defaults.graph_expansion_hops,
                "max_expansion_nodes": defaults.max_expansion_nodes,
                "max_symbols_per_chunk": defaults.max_symbols_per_chunk,
                "max_resolved_ids_per_symbol": defaults.max_resolved_ids_per_symbol,
                "max_entry_points_traced": defaults.max_entry_points_traced,
                "max_context_items_for_flow": defaults.max_context_items_for_flow,
                "same_file_bonus": defaults.same_file_bonus,
                "same_directory_bonus": defaults.same_directory_bonus,
                "tokens_per_line": defaults.tokens_per_line,
                "max_depth": defaults.max_depth,
                "similarity_threshold": defaults.similarity_threshold,
                "similarity_function": defaults.similarity_function,
                "include_visualization": defaults.include_visualization,
                "include_related_symbols": defaults.include_related_symbols,
                "enable_ranking": defaults.enable_ranking,
            }
    except (ImportError, AttributeError):
        pass

    # Fallback to hardcoded defaults if settings not available
    return {
        "max_context_tokens": 100000,
        "top_k_vector": 200,
        "graph_expansion_hops": 5,
        "max_expansion_nodes": 500,
        "max_symbols_per_chunk": 3,
        "max_resolved_ids_per_symbol": 3,
        "max_entry_points_traced": 5,
        "max_context_items_for_flow": 10,
        "same_file_bonus": 0.1,
        "same_directory_bonus": 0.05,
        "tokens_per_line": 10.0,
        "max_depth": 25,
        "similarity_threshold": 0.7,
        "similarity_function": "cosine",
        "include_visualization": True,
        "include_related_symbols": True,
        "enable_ranking": True,  # Default to enabled
    }


@dataclass
class RetrievalConfig:
    """Configuration for retrieval operations.

    This dataclass holds all configurable parameters for retrieval operations,
    including graph traversal, vector search, and context management settings.

    Default values are loaded from settings.yaml via settings.retrieval_defaults.
    """

    # Core retrieval parameters
    max_context_tokens: int = field(
        default_factory=lambda: _get_default_retrieval_values()["max_context_tokens"]
    )
    top_k_vector: int = field(
        default_factory=lambda: _get_default_retrieval_values()["top_k_vector"]
    )
    graph_expansion_hops: int = field(
        default_factory=lambda: _get_default_retrieval_values()["graph_expansion_hops"]
    )
    max_expansion_nodes: int = field(
        default_factory=lambda: _get_default_retrieval_values()["max_expansion_nodes"]
    )
    max_symbols_per_chunk: int = field(
        default_factory=lambda: _get_default_retrieval_values()["max_symbols_per_chunk"]
    )
    max_resolved_ids_per_symbol: int = field(
        default_factory=lambda: _get_default_retrieval_values()[
            "max_resolved_ids_per_symbol"
        ]
    )
    max_entry_points_traced: int = field(
        default_factory=lambda: _get_default_retrieval_values()[
            "max_entry_points_traced"
        ]
    )
    max_context_items_for_flow: int = field(
        default_factory=lambda: _get_default_retrieval_values()[
            "max_context_items_for_flow"
        ]
    )
    same_file_bonus: float = field(
        default_factory=lambda: _get_default_retrieval_values()["same_file_bonus"]
    )
    same_directory_bonus: float = field(
        default_factory=lambda: _get_default_retrieval_values()["same_directory_bonus"]
    )
    tokens_per_line: float = field(
        default_factory=lambda: _get_default_retrieval_values()["tokens_per_line"]
    )

    # Graph traversal parameters
    max_depth: int = field(
        default_factory=lambda: _get_default_retrieval_values()["max_depth"]
    )

    # Semantic matching parameters
    similarity_threshold: float = field(
        default_factory=lambda: _get_default_retrieval_values()["similarity_threshold"]
    )
    similarity_function: str = field(
        default_factory=lambda: _get_default_retrieval_values()["similarity_function"]
    )

    # Feature toggles
    include_visualization: bool = field(
        default_factory=lambda: _get_default_retrieval_values()["include_visualization"]
    )
    include_related_symbols: bool = field(
        default_factory=lambda: _get_default_retrieval_values()[
            "include_related_symbols"
        ]
    )
    enable_ranking: bool = field(
        default_factory=lambda: _get_default_retrieval_values()["enable_ranking"]
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation of the config.
        """
        return {
            "max_context_tokens": self.max_context_tokens,
            "top_k_vector": self.top_k_vector,
            "graph_expansion_hops": self.graph_expansion_hops,
            "max_expansion_nodes": self.max_expansion_nodes,
            "max_symbols_per_chunk": self.max_symbols_per_chunk,
            "max_resolved_ids_per_symbol": self.max_resolved_ids_per_symbol,
            "max_entry_points_traced": self.max_entry_points_traced,
            "max_context_items_for_flow": self.max_context_items_for_flow,
            "same_file_bonus": self.same_file_bonus,
            "same_directory_bonus": self.same_directory_bonus,
            "tokens_per_line": self.tokens_per_line,
            "max_depth": self.max_depth,
            "similarity_threshold": self.similarity_threshold,
            "similarity_function": self.similarity_function,
            "include_visualization": self.include_visualization,
            "include_related_symbols": self.include_related_symbols,
            "enable_ranking": self.enable_ranking,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrievalConfig":
        """Create from dictionary.

        Args:
            data: Dictionary with config values. Missing keys will use class defaults.

        Returns:
            RetrievalConfig instance with values from dictionary.
        """
        # Start with defaults, then overlay provided data
        # This ensures all missing keys use class defaults
        defaults_dict = cls().to_dict()
        defaults_dict.update(data)

        config = cls(**defaults_dict)
        config.validate()
        return config

    def to_json(self) -> str:
        """Serialize to JSON string.

        Returns:
            JSON string representation of the config.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "RetrievalConfig":
        """Deserialize from JSON string.

        Args:
            json_str: JSON string with config values.

        Returns:
            RetrievalConfig instance with values from JSON.
        """
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def get_defaults(cls) -> "RetrievalConfig":
        """Get a new instance with default values.

        Returns:
            RetrievalConfig instance with all default values.
        """
        return cls()

    @classmethod
    def from_settings(cls, settings_obj=None) -> "RetrievalConfig":
        """Create RetrievalConfig from application settings.

        Args:
            settings_obj: Optional settings object with retrieval_defaults.
                         If None, imports and uses global settings.

        Returns:
            RetrievalConfig instance with values from settings.
        """
        if settings_obj is None:
            try:
                from graph_kb_api.config import settings as app_settings

                settings_obj = app_settings
            except ImportError:
                # Fallback to defaults if settings not available
                return cls()

        # Use retrieval_defaults from settings if available
        if hasattr(settings_obj, "retrieval_defaults"):
            defaults = settings_obj.retrieval_defaults
            return cls(
                max_context_tokens=defaults.max_context_tokens,
                top_k_vector=defaults.top_k_vector,
                graph_expansion_hops=defaults.graph_expansion_hops,
                max_expansion_nodes=defaults.max_expansion_nodes,
                max_symbols_per_chunk=defaults.max_symbols_per_chunk,
                max_resolved_ids_per_symbol=defaults.max_resolved_ids_per_symbol,
                max_entry_points_traced=defaults.max_entry_points_traced,
                max_context_items_for_flow=defaults.max_context_items_for_flow,
                same_file_bonus=defaults.same_file_bonus,
                same_directory_bonus=defaults.same_directory_bonus,
                tokens_per_line=defaults.tokens_per_line,
                max_depth=defaults.max_depth,
                similarity_threshold=defaults.similarity_threshold,
                similarity_function=defaults.similarity_function,
                include_visualization=defaults.include_visualization,
                include_related_symbols=defaults.include_related_symbols,
                enable_ranking=defaults.enable_ranking,
            )
        else:
            # Fallback to class defaults
            return cls()

    def validate(self) -> None:
        """Validate and clamp values to valid ranges.

        This method clamps values to valid ranges rather than raising errors,
        ensuring the config is always usable. Ranges come from settings.yaml
        chat_ui_sliders configuration.
        """
        # Try to load validation ranges from settings
        try:
            from graph_kb_api.config import settings

            if hasattr(settings, "chat_ui_sliders"):
                sliders = settings.chat_ui_sliders

                # Clamp values using slider configs
                self.max_context_tokens = max(
                    int(sliders.max_context_tokens.min),
                    min(self.max_context_tokens, int(sliders.max_context_tokens.max)),
                )
                self.top_k_vector = max(
                    int(sliders.top_k.min),
                    min(self.top_k_vector, int(sliders.top_k.max)),
                )
                self.graph_expansion_hops = max(
                    int(sliders.expansion_hops.min),
                    min(self.graph_expansion_hops, int(sliders.expansion_hops.max)),
                )
                self.same_file_bonus = max(
                    sliders.same_file_bonus.min,
                    min(self.same_file_bonus, sliders.same_file_bonus.max),
                )
                self.same_directory_bonus = max(
                    sliders.same_directory_bonus.min,
                    min(self.same_directory_bonus, sliders.same_directory_bonus.max),
                )
                self.max_depth = max(
                    int(sliders.max_depth.min),
                    min(self.max_depth, int(sliders.max_depth.max)),
                )
                self.max_expansion_nodes = max(
                    int(sliders.max_expansion_nodes.min),
                    min(self.max_expansion_nodes, int(sliders.max_expansion_nodes.max)),
                )

                # For fields without sliders, use reasonable ranges
                self.similarity_threshold = max(
                    0.0, min(self.similarity_threshold, 1.0)
                )
                self.tokens_per_line = max(1.0, min(self.tokens_per_line, 500.0))

                # Validate similarity_function
                if self.similarity_function not in ("cosine", "euclidean"):
                    self.similarity_function = "cosine"

                return
        except (ImportError, AttributeError):
            pass

        # Fallback validation with hardcoded ranges if settings not available
        self.max_context_tokens = max(1000, min(self.max_context_tokens, 200000))
        self.top_k_vector = max(5, min(self.top_k_vector, 5000))
        self.graph_expansion_hops = max(1, min(self.graph_expansion_hops, 10))
        self.max_expansion_nodes = max(100, min(self.max_expansion_nodes, 2000))
        self.max_depth = max(1, min(self.max_depth, 100))
        self.similarity_threshold = max(0.0, min(self.similarity_threshold, 1.0))
        self.same_file_bonus = max(0.0, min(self.same_file_bonus, 1.0))
        self.same_directory_bonus = max(0.0, min(self.same_directory_bonus, 1.0))
        self.tokens_per_line = max(1.0, min(self.tokens_per_line, 500.0))

        # Validate similarity_function
        if self.similarity_function not in ("cosine", "euclidean"):
            self.similarity_function = "cosine"
