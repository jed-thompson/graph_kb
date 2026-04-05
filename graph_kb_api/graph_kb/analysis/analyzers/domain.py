"""Domain Extractor V2 for identifying business domain concepts using neo4j-graphrag.

This module provides the DomainExtractorV2 class that identifies classes and functions
that represent business entities, services, repositories, and other domain concepts,
leveraging the GraphRetrieverAdapter for graph queries.
"""

import json
import re
from typing import Any, Dict, List, Optional, Set

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...adapters.storage.graph_retriever import GraphRetrieverAdapter
from ...models.analysis import DomainConcept, DomainRelationship
from ...models.analysis_enums import DomainCategory, RelationType

logger = EnhancedLogger(__name__)


# Naming patterns for domain category classification
ENTITY_PATTERNS = [
    r"Model$",
    r"Entity$",
    r"^Base[A-Z]",
]

ENTITY_FILE_PATTERNS = [
    r"/models?/",
    r"/entities?/",
    r"/domain/",
]

SERVICE_PATTERNS = [
    r"Service$",
    r"Manager$",
    r"Handler$",
    r"Controller$",
    r"Processor$",
    r"Provider$",
]

REPOSITORY_PATTERNS = [
    r"Repository$",
    r"Repo$",
    r"DAO$",
    r"Store$",
    r"Gateway$",
]

UTILITY_PATTERNS = [
    r"Utils?$",
    r"Helper$",
    r"Util$",
    r"Helpers?$",
    r"Mixin$",
]

VALUE_OBJECT_PATTERNS = [
    r"DTO$",
    r"Request$",
    r"Response$",
    r"Schema$",
    r"Params?$",
    r"Config$",
    r"Settings$",
    r"Options$",
]

# Base class patterns for inheritance-based classification
ENTITY_BASE_CLASSES = {
    "model", "basemodel", "entity", "base", "dbmodel",
    "sqlalchemybase", "declarativebase", "pydanticmodel",
}

SERVICE_BASE_CLASSES = {
    "service", "baseservice", "abstractservice",
}

REPOSITORY_BASE_CLASSES = {
    "repository", "baserepository", "abstractrepository",
}


class DomainExtractorV2:
    """Extractor for identifying business domain concepts using neo4j-graphrag.

    Domain concepts are classes that represent business entities, services,
    repositories, utilities, and value objects. Classification uses:
    1. Naming patterns (e.g., UserService, OrderRepository)
    2. Inheritance (e.g., extends Model, BaseEntity)
    3. File location (e.g., models/, services/)
    """

    def __init__(self, retriever: GraphRetrieverAdapter):
        """Initialize the DomainExtractorV2.

        Args:
            retriever: The GraphRetrieverAdapter for graph queries.
        """
        self._retriever = retriever

    def extract(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[DomainConcept]:
        """Extract domain concepts from a repository.

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            List of discovered DomainConcept objects.
        """
        # Get all class symbols
        class_symbols = self._retriever.find_classes(repo_id, folder_path)

        # Build inheritance map for classification
        inheritance_map = self._build_inheritance_map(repo_id, class_symbols)

        # Classify each class symbol
        concepts: List[DomainConcept] = []
        concept_ids: Set[str] = set()

        for symbol_data in class_symbols:
            symbol_id = symbol_data.get("id", "")
            attrs = self._parse_attrs(symbol_data.get("attrs", "{}"))

            # Apply folder filter if specified
            file_path = attrs.get("file_path", "")
            if folder_path and not file_path.startswith(folder_path):
                continue

            category = self._classify_domain_concept(attrs, inheritance_map.get(symbol_id, []))
            if category is not None:
                concept = self._create_domain_concept(symbol_id, attrs, category)
                concepts.append(concept)
                concept_ids.add(symbol_id)

        # Extract relationships between concepts
        self._extract_relationships(repo_id, concepts, concept_ids)

        # Sort by category and then by name for consistent ordering
        concepts.sort(key=lambda c: (c.category.value, c.name))

        return concepts

    def _parse_attrs(self, attrs: Any) -> Dict[str, Any]:
        """Parse symbol attributes from string or dict.

        Args:
            attrs: The attributes as string or dict.

        Returns:
            Parsed attributes dictionary.
        """
        if isinstance(attrs, str):
            try:
                return json.loads(attrs)
            except json.JSONDecodeError:
                return {}
        elif isinstance(attrs, dict):
            return attrs
        return {}

    def _build_inheritance_map(
        self,
        repo_id: str,
        class_symbols: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        """Build a map of class IDs to their base class names.

        Args:
            repo_id: The repository ID for repository-aware edge detection.
            class_symbols: List of class symbol dictionaries.

        Returns:
            Dictionary mapping class ID to list of base class names.
        """
        inheritance_map: Dict[str, List[str]] = {}

        for symbol_data in class_symbols:
            symbol_id = symbol_data.get("id", "")
            if not symbol_id:
                continue

            # Get reachable subgraph via EXTENDS relationship
            try:
                result = self._retriever.get_reachable_subgraph(
                    start_id=symbol_id,
                    max_depth=1,
                    edge_types=["EXTENDS"],
                    direction="outgoing",
                )

                base_names = []
                for node in result.nodes:
                    if node.id != symbol_id:
                        base_name = node.attrs.get("name", "")
                        if base_name:
                            base_names.append(base_name.lower())

                inheritance_map[symbol_id] = base_names
            except Exception:
                inheritance_map[symbol_id] = []

        return inheritance_map

    def _classify_domain_concept(
        self,
        attrs: Dict[str, Any],
        base_classes: List[str],
    ) -> Optional[DomainCategory]:
        """Classify a class symbol as a domain concept category.

        Classification priority:
        1. Inheritance-based (most reliable)
        2. Name pattern-based
        3. File location-based

        Args:
            attrs: The symbol attributes.
            base_classes: List of base class names (lowercase).

        Returns:
            DomainCategory if classified, None if not a domain concept.
        """
        name = attrs.get("name", "")
        file_path = attrs.get("file_path", "").lower()

        # 1. Check inheritance-based classification (highest priority)
        category = self._classify_by_inheritance(base_classes)
        if category is not None:
            return category

        # 2. Check name pattern-based classification
        category = self._classify_by_name(name)
        if category is not None:
            return category

        # 3. Check file location-based classification
        category = self._classify_by_file_path(file_path)
        if category is not None:
            return category

        return None

    def _classify_by_inheritance(
        self,
        base_classes: List[str],
    ) -> Optional[DomainCategory]:
        """Classify based on inheritance from known base classes.

        Args:
            base_classes: List of base class names (lowercase).

        Returns:
            DomainCategory if matched, None otherwise.
        """
        for base in base_classes:
            if base in ENTITY_BASE_CLASSES:
                return DomainCategory.ENTITY
            if base in SERVICE_BASE_CLASSES:
                return DomainCategory.SERVICE
            if base in REPOSITORY_BASE_CLASSES:
                return DomainCategory.REPOSITORY

        return None

    def _classify_by_name(self, name: str) -> Optional[DomainCategory]:
        """Classify based on class name patterns.

        Args:
            name: The class name.

        Returns:
            DomainCategory if matched, None otherwise.
        """
        # Check patterns in order of specificity
        # Repository patterns (most specific)
        if any(re.search(p, name) for p in REPOSITORY_PATTERNS):
            return DomainCategory.REPOSITORY

        # Service patterns
        if any(re.search(p, name) for p in SERVICE_PATTERNS):
            return DomainCategory.SERVICE

        # Value object patterns
        if any(re.search(p, name) for p in VALUE_OBJECT_PATTERNS):
            return DomainCategory.VALUE_OBJECT

        # Utility patterns
        if any(re.search(p, name) for p in UTILITY_PATTERNS):
            return DomainCategory.UTILITY

        # Entity patterns (least specific, checked last)
        if any(re.search(p, name) for p in ENTITY_PATTERNS):
            return DomainCategory.ENTITY

        return None

    def _classify_by_file_path(self, file_path: str) -> Optional[DomainCategory]:
        """Classify based on file path patterns.

        Args:
            file_path: The file path (lowercase).

        Returns:
            DomainCategory if matched, None otherwise.
        """
        # Only use file path for entity classification
        # Other categories are too ambiguous based on file path alone
        if any(re.search(p, file_path) for p in ENTITY_FILE_PATTERNS):
            return DomainCategory.ENTITY

        return None

    def _create_domain_concept(
        self,
        symbol_id: str,
        attrs: Dict[str, Any],
        category: DomainCategory,
    ) -> DomainConcept:
        """Create a DomainConcept from symbol attributes and its category.

        Args:
            symbol_id: The symbol ID.
            attrs: The symbol attributes.
            category: The classified domain category.

        Returns:
            A DomainConcept object.
        """
        return DomainConcept(
            id=symbol_id,
            name=attrs.get("name", ""),
            category=category,
            file_path=attrs.get("file_path", ""),
            description=attrs.get("docstring"),
            relationships=[],
        )

    def _extract_relationships(
        self,
        repo_id: str,
        concepts: List[DomainConcept],
        concept_ids: Set[str],
    ) -> None:
        """Extract relationships between domain concepts.

        Modifies concepts in place to add relationships.

        Args:
            repo_id: The repository ID for repository-aware edge detection.
            concepts: List of domain concepts to update.
            concept_ids: Set of all concept IDs for filtering.
        """
        concept_map = {c.id: c for c in concepts}

        for concept in concepts:
            relationships = self._get_concept_relationships(
                repo_id,
                concept.id,
                concept_ids,
                concept_map,
            )
            concept.relationships.extend(relationships)

    def _get_concept_relationships(
        self,
        repo_id: str,
        concept_id: str,
        concept_ids: Set[str],
        concept_map: Dict[str, DomainConcept],
    ) -> List[DomainRelationship]:
        """Get relationships for a single concept.

        Args:
            repo_id: The repository ID for repository-aware edge detection.
            concept_id: The concept's ID.
            concept_ids: Set of all concept IDs.
            concept_map: Map of concept IDs to concepts.

        Returns:
            List of DomainRelationship objects.
        """
        relationships: List[DomainRelationship] = []
        seen_targets: Set[str] = set()

        # Check EXTENDS relationships (inheritance)
        try:
            extends_result = self._retriever.get_reachable_subgraph(
                start_id=concept_id,
                max_depth=1,
                edge_types=["EXTENDS"],
                direction="outgoing",
            )
            for node in extends_result.nodes:
                if node.id != concept_id and node.id in concept_ids and node.id not in seen_targets:
                    target = concept_map.get(node.id)
                    if target:
                        relationships.append(DomainRelationship(
                            target_concept_id=node.id,
                            target_concept_name=target.name,
                            relationship_type=RelationType.EXTENDS,
                        ))
                        seen_targets.add(node.id)
        except Exception:
            pass

        # Check CALLS/IMPORTS relationships (uses)
        try:
            uses_result = self._retriever.get_reachable_subgraph(
                start_id=concept_id,
                max_depth=1,
                edge_types=["CALLS", "IMPORTS"],
                direction="outgoing",
            )
            for node in uses_result.nodes:
                if node.id != concept_id and node.id in concept_ids and node.id not in seen_targets:
                    target = concept_map.get(node.id)
                    if target:
                        rel_type = self._infer_relationship_type(concept_map.get(concept_id), target)
                        relationships.append(DomainRelationship(
                            target_concept_id=node.id,
                            target_concept_name=target.name,
                            relationship_type=rel_type,
                        ))
                        seen_targets.add(node.id)
        except Exception:
            pass

        return relationships

    def _infer_relationship_type(
        self,
        source: Optional[DomainConcept],
        target: Optional[DomainConcept],
    ) -> RelationType:
        """Infer the relationship type between two concepts.

        Args:
            source: The source concept.
            target: The target concept.

        Returns:
            The inferred RelationType.
        """
        if source is None or target is None:
            return RelationType.USES

        # Service using Repository -> USES
        if source.category == DomainCategory.SERVICE and target.category == DomainCategory.REPOSITORY:
            return RelationType.USES

        # Entity referencing Entity -> could be HAS_MANY or BELONGS_TO
        if source.category == DomainCategory.ENTITY and target.category == DomainCategory.ENTITY:
            # Heuristic: if target name is in source name, likely BELONGS_TO
            # e.g., OrderItem belongs_to Order
            if target.name.lower() in source.name.lower():
                return RelationType.BELONGS_TO
            # Otherwise assume HAS_MANY
            return RelationType.HAS_MANY

        # Default to USES
        return RelationType.USES
