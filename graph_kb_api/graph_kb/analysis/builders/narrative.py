"""Narrative Generator V2 for creating human-readable codebase summaries.

This module provides the NarrativeGeneratorV2 class that generates narrative
summaries of codebases using neo4j-graphrag's LLM integration via LLMAdapter.
"""

from typing import List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...adapters.external.llm_adapter import LLMAdapter
from ...models import LLMNotConfiguredError
from ...models.analysis import DomainConcept, EntryPoint, NarrativeSummary

logger = EnhancedLogger(__name__)


# System prompt for narrative generation
NARRATIVE_SYSTEM_PROMPT = """You are a technical documentation expert. Your task is to generate a clear,
concise narrative summary of a codebase based on its entry points and domain concepts.

Your response MUST be in the following exact format with these section headers:

PURPOSE:
[A single paragraph describing the overall purpose of the codebase]

CAPABILITIES:
- [Capability 1]
- [Capability 2]
- [Additional capabilities as bullet points]

COMPONENTS:
- [Component 1]
- [Component 2]
- [Additional components as bullet points]

HOW IT WORKS:
[Explain how the components work together]

FULL NARRATIVE:
[A comprehensive summary combining all the above information]

Important guidelines:
- Be specific and technical but accessible
- Focus on what the code does, not how it's implemented
- Use the entry points to understand user-facing functionality
- Use domain concepts to understand the business model
- If information is limited, make reasonable inferences from naming conventions
"""


class NarrativeGeneratorV2:
    """Generator for creating human-readable narrative summaries of codebases.

    Uses neo4j-graphrag's LLMInterface (via LLMAdapter) to combine entry point
    and domain concept information into coherent prose descriptions.

    This V2 implementation is designed to work with neo4j-graphrag components.
    """

    def __init__(self, llm_adapter: Optional[LLMAdapter] = None):
        """Initialize the NarrativeGeneratorV2.

        Args:
            llm_adapter: Optional LLMAdapter instance. If not provided,
                        narrative generation will not be available.
        """
        self._llm_adapter = llm_adapter

    @property
    def is_configured(self) -> bool:
        """Check if the LLM is configured for narrative generation.

        Returns:
            True if LLM adapter is configured, False otherwise.
        """
        return self._llm_adapter is not None and self._llm_adapter.is_configured

    async def generate(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
    ) -> NarrativeSummary:
        """Generate a narrative summary for a repository.

        Uses the LLM to generate a human-readable narrative describing
        the repository's purpose, capabilities, and structure.

        Args:
            repo_id: The repository ID.
            entry_points: List of discovered entry points.
            domain_concepts: List of discovered domain concepts.

        Returns:
            A NarrativeSummary containing the generated narrative.

        Raises:
            LLMNotConfiguredError: If no LLM is configured (when skip_if_not_configured=False).
        """
        # Check if LLM is configured
        if not self.is_configured:
            logger.info("LLM not configured, returning fallback narrative")
            return self._create_fallback_narrative(
                repo_id, entry_points, domain_concepts, "LLM not configured"
            )

        try:
            # Use the LLM adapter to generate the narrative
            return await self._llm_adapter.generate_narrative(
                repo_id=repo_id,
                entry_points=entry_points,
                domain_concepts=domain_concepts,
            )
        except LLMNotConfiguredError:
            # LLM not configured - return fallback
            logger.info("LLM not configured, returning fallback narrative")
            return self._create_fallback_narrative(
                repo_id, entry_points, domain_concepts, "LLM not configured"
            )
        except Exception as e:
            # Handle LLM failures gracefully
            logger.warning(f"LLM generation failed: {e}")
            return self._create_fallback_narrative(
                repo_id, entry_points, domain_concepts, str(e)
            )

    def generate_sync(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
    ) -> NarrativeSummary:
        """Synchronous version of generate.

        Args:
            repo_id: The repository ID.
            entry_points: List of discovered entry points.
            domain_concepts: List of discovered domain concepts.

        Returns:
            A NarrativeSummary containing the generated narrative.
        """
        # Check if LLM is configured
        if not self.is_configured:
            logger.info("LLM not configured, returning fallback narrative")
            return self._create_fallback_narrative(
                repo_id, entry_points, domain_concepts, "LLM not configured"
            )

        try:
            # Use the LLM adapter to generate the narrative (sync)
            return self._llm_adapter.generate_narrative_sync(
                repo_id=repo_id,
                entry_points=entry_points,
                domain_concepts=domain_concepts,
            )
        except LLMNotConfiguredError:
            # LLM not configured - return fallback
            logger.info("LLM not configured, returning fallback narrative")
            return self._create_fallback_narrative(
                repo_id, entry_points, domain_concepts, "LLM not configured"
            )
        except Exception as e:
            # Handle LLM failures gracefully
            logger.warning(f"LLM generation failed: {e}")
            return self._create_fallback_narrative(
                repo_id, entry_points, domain_concepts, str(e)
            )

    def _create_fallback_narrative(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
        error_message: str,
    ) -> NarrativeSummary:
        """Create a fallback narrative when LLM generation fails or is not configured.

        Provides a partial result with basic information extracted from
        the analysis results.

        Args:
            repo_id: The repository ID.
            entry_points: List of discovered entry points.
            domain_concepts: List of discovered domain concepts.
            error_message: Error message from the failed generation.

        Returns:
            A minimal NarrativeSummary based on available data.
        """
        # Build purpose from entry points
        if entry_points:
            ep_types = set(ep.entry_type.value for ep in entry_points)
            purpose = f"Repository {repo_id} provides {', '.join(sorted(ep_types))} functionality."
        else:
            purpose = f"Repository {repo_id} (narrative generation unavailable: {error_message})"

        # Build capabilities from entry point types
        capabilities = []
        entry_point_types = set(ep.entry_type.value for ep in entry_points)
        if "http_endpoint" in entry_point_types:
            capabilities.append("HTTP API endpoints")
        if "cli_command" in entry_point_types:
            capabilities.append("Command-line interface")
        if "main_function" in entry_point_types:
            capabilities.append("Standalone execution")
        if "event_handler" in entry_point_types:
            capabilities.append("Event handling")
        if "scheduled_task" in entry_point_types:
            capabilities.append("Scheduled tasks")

        # Add specific entry point names as capabilities (limit to 5)
        for ep in entry_points[:5]:
            cap = f"{ep.name} ({ep.entry_type.value})"
            if cap not in capabilities:
                capabilities.append(cap)

        # Build components from domain concepts (limit to 10)
        components = [dc.name for dc in domain_concepts[:10]]

        # Build how_it_works
        if entry_points and domain_concepts:
            how_it_works = (
                f"The system exposes {len(entry_points)} entry points that interact "
                f"with {len(domain_concepts)} domain concepts."
            )
        elif entry_points:
            how_it_works = f"The system exposes {len(entry_points)} entry points."
        elif domain_concepts:
            how_it_works = f"The system contains {len(domain_concepts)} domain concepts."
        else:
            how_it_works = "System structure could not be determined."

        # Build full narrative
        full_narrative = purpose
        if capabilities:
            full_narrative += f" Key capabilities include: {', '.join(capabilities[:3])}."
        if components:
            full_narrative += f" Core components include: {', '.join(components[:3])}."
        full_narrative += f" Note: Full narrative generation unavailable ({error_message})."

        return NarrativeSummary(
            repo_id=repo_id,
            purpose=purpose,
            capabilities=capabilities,
            components=components,
            how_it_works=how_it_works,
            full_narrative=full_narrative,
        )

    def _build_prompt(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
    ) -> str:
        """Build the user prompt from entry points and domain concepts.

        This method is provided for testing and customization purposes.
        The actual prompt building is delegated to the LLMAdapter.

        Args:
            repo_id: The repository ID.
            entry_points: List of discovered entry points.
            domain_concepts: List of discovered domain concepts.

        Returns:
            The formatted user prompt string.
        """
        lines = [f"Generate a narrative summary for repository: {repo_id}\n"]

        # Add entry points section
        lines.append("## Entry Points\n")
        if entry_points:
            for ep in entry_points[:20]:  # Limit to 20
                ep_line = f"- {ep.name} ({ep.entry_type.value})"
                if ep.http_method:
                    ep_line += f" [{ep.http_method}]"
                if ep.description:
                    ep_line += f": {ep.description}"
                lines.append(ep_line)
        else:
            lines.append("No entry points discovered.")

        lines.append("")

        # Add domain concepts section
        lines.append("## Domain Concepts\n")
        if domain_concepts:
            for dc in domain_concepts[:20]:  # Limit to 20
                dc_line = f"- {dc.name} ({dc.category.value})"
                if dc.description:
                    dc_line += f": {dc.description}"
                lines.append(dc_line)

                # Add relationships if present
                for rel in dc.relationships[:5]:  # Limit to 5 relationships
                    lines.append(f"  - {rel.relationship_type.value} {rel.target_concept_name}")
        else:
            lines.append("No domain concepts discovered.")

        return "\n".join(lines)
