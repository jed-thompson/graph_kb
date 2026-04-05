"""Adapter for neo4j-graphrag LLMInterface for narrative generation.

This module wraps neo4j-graphrag's LLM capabilities for generating
human-readable narrative summaries of code analysis results.
"""

from typing import Any, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models import LLMNotConfiguredError
from ...models.analysis import (
    DomainConcept,
    EntryPoint,
    NarrativeSummary,
)

logger = EnhancedLogger(__name__)


class LLMAdapter:
    """Adapter for neo4j-graphrag LLMInterface for narrative generation.

    Provides methods for generating human-readable narrative summaries
    from code analysis results using LLM integration.
    """

    def __init__(
        self,
        llm: Optional[Any] = None,  # neo4j_graphrag.llm.LLMInterface
        model: str = "gpt-4",
    ):
        """Initialize the adapter with an LLM instance.

        Args:
            llm: Optional LLMInterface instance. If not provided, will attempt
                 to create an OpenAI LLM with the specified model.
            model: Model name to use if creating a new LLM instance
        """
        self._llm = llm
        self._model = model
        self._is_configured = llm is not None

    @property
    def is_configured(self) -> bool:
        """Check if the LLM is configured."""
        return self._is_configured

    async def generate_narrative(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
    ) -> NarrativeSummary:
        """Generate a narrative summary from analysis results.

        Uses the LLM to generate a human-readable narrative describing
        the repository's purpose, capabilities, and structure.

        Args:
            repo_id: Repository identifier
            entry_points: List of discovered entry points
            domain_concepts: List of extracted domain concepts

        Returns:
            NarrativeSummary containing the generated narrative

        Raises:
            LLMNotConfiguredError: If no LLM is configured
        """
        if not self._is_configured:
            raise LLMNotConfiguredError("LLM is not configured for narrative generation")

        # Build the prompt
        prompt = self._build_narrative_prompt(repo_id, entry_points, domain_concepts)

        try:
            # Generate response using the LLM
            response = await self._llm.ainvoke(prompt)

            # Parse the response into a NarrativeSummary
            return self._parse_narrative_response(repo_id, response)
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            # Return a partial result with error indication
            return self._create_fallback_narrative(repo_id, entry_points, domain_concepts, str(e))

    def generate_narrative_sync(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
    ) -> NarrativeSummary:
        """Synchronous version of generate_narrative.

        Args:
            repo_id: Repository identifier
            entry_points: List of discovered entry points
            domain_concepts: List of extracted domain concepts

        Returns:
            NarrativeSummary containing the generated narrative

        Raises:
            LLMNotConfiguredError: If no LLM is configured
        """
        if not self._is_configured:
            raise LLMNotConfiguredError("LLM is not configured for narrative generation")

        # Build the prompt
        prompt = self._build_narrative_prompt(repo_id, entry_points, domain_concepts)

        try:
            # Generate response using the LLM (synchronous)
            response = self._llm.invoke(prompt)

            # Parse the response into a NarrativeSummary
            return self._parse_narrative_response(repo_id, response)
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            # Return a partial result with error indication
            return self._create_fallback_narrative(repo_id, entry_points, domain_concepts, str(e))

    def _build_narrative_prompt(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
    ) -> str:
        """Build the prompt for narrative generation.

        Args:
            repo_id: Repository identifier
            entry_points: List of discovered entry points
            domain_concepts: List of extracted domain concepts

        Returns:
            Formatted prompt string
        """
        lines = [
            "You are a technical writer analyzing a codebase. Based on the following analysis results,",
            "generate a comprehensive narrative summary of the repository.",
            "",
            f"Repository: {repo_id}",
            "",
            "## Entry Points",
            "",
        ]

        if entry_points:
            for ep in entry_points[:20]:  # Limit to 20 entry points
                lines.append(f"- {ep.name} ({ep.entry_type.value})")
                if ep.description:
                    lines.append(f"  Description: {ep.description}")
                if ep.http_method and ep.route:
                    lines.append(f"  Route: {ep.http_method} {ep.route}")
        else:
            lines.append("No entry points discovered.")

        lines.extend([
            "",
            "## Domain Concepts",
            "",
        ])

        if domain_concepts:
            for dc in domain_concepts[:20]:  # Limit to 20 concepts
                lines.append(f"- {dc.name} ({dc.category.value})")
                if dc.description:
                    lines.append(f"  Description: {dc.description}")
                if dc.relationships:
                    rel_strs = [f"{r.target_concept_name} ({r.relationship_type.value})"
                               for r in dc.relationships[:5]]
                    lines.append(f"  Relationships: {', '.join(rel_strs)}")
        else:
            lines.append("No domain concepts extracted.")

        lines.extend([
            "",
            "## Instructions",
            "",
            "Please provide:",
            "1. A one-sentence purpose statement",
            "2. A list of 3-5 key capabilities",
            "3. A list of main components",
            "4. A paragraph explaining how the system works",
            "5. A full narrative summary (2-3 paragraphs)",
            "",
            "Format your response as follows:",
            "PURPOSE: <purpose statement>",
            "CAPABILITIES:",
            "- <capability 1>",
            "- <capability 2>",
            "...",
            "COMPONENTS:",
            "- <component 1>",
            "- <component 2>",
            "...",
            "HOW_IT_WORKS: <explanation paragraph>",
            "NARRATIVE: <full narrative>",
        ])

        return "\n".join(lines)

    def _parse_narrative_response(
        self,
        repo_id: str,
        response: str,
    ) -> NarrativeSummary:
        """Parse the LLM response into a NarrativeSummary.

        Args:
            repo_id: Repository identifier
            response: Raw LLM response text

        Returns:
            Parsed NarrativeSummary
        """
        # Default values
        purpose = ""
        capabilities: List[str] = []
        components: List[str] = []
        how_it_works = ""
        full_narrative = ""

        # Parse the response
        current_section = None
        lines = response.split("\n")

        for line in lines:
            line = line.strip()

            if line.startswith("PURPOSE:"):
                purpose = line[8:].strip()
                current_section = None
            elif line.startswith("CAPABILITIES:"):
                current_section = "capabilities"
            elif line.startswith("COMPONENTS:"):
                current_section = "components"
            elif line.startswith("HOW_IT_WORKS:"):
                how_it_works = line[13:].strip()
                current_section = "how_it_works"
            elif line.startswith("NARRATIVE:"):
                full_narrative = line[10:].strip()
                current_section = "narrative"
            elif line.startswith("- ") and current_section == "capabilities":
                capabilities.append(line[2:].strip())
            elif line.startswith("- ") and current_section == "components":
                components.append(line[2:].strip())
            elif current_section == "how_it_works" and line:
                how_it_works += " " + line
            elif current_section == "narrative" and line:
                full_narrative += " " + line

        return NarrativeSummary(
            repo_id=repo_id,
            purpose=purpose.strip(),
            capabilities=capabilities,
            components=components,
            how_it_works=how_it_works.strip(),
            full_narrative=full_narrative.strip(),
        )

    def _create_fallback_narrative(
        self,
        repo_id: str,
        entry_points: List[EntryPoint],
        domain_concepts: List[DomainConcept],
        error_message: str,
    ) -> NarrativeSummary:
        """Create a fallback narrative when LLM generation fails.

        Args:
            repo_id: Repository identifier
            entry_points: List of discovered entry points
            domain_concepts: List of extracted domain concepts
            error_message: Error message from the failed generation

        Returns:
            Fallback NarrativeSummary with basic information
        """
        # Extract basic information from the analysis results
        entry_point_types = set(ep.entry_type.value for ep in entry_points)
        concept_categories = set(dc.category.value for dc in domain_concepts)

        purpose = f"Repository {repo_id} (narrative generation failed: {error_message})"

        capabilities = []
        if "http_endpoint" in entry_point_types:
            capabilities.append("HTTP API endpoints")
        if "cli_command" in entry_point_types:
            capabilities.append("Command-line interface")
        if "main_function" in entry_point_types:
            capabilities.append("Standalone execution")

        components = [dc.name for dc in domain_concepts[:10]]

        how_it_works = (
            f"This repository contains {len(entry_points)} entry points "
            f"and {len(domain_concepts)} domain concepts."
        )

        full_narrative = (
            f"Analysis of {repo_id} identified {len(entry_points)} entry points "
            f"across {len(entry_point_types)} types and {len(domain_concepts)} "
            f"domain concepts across {len(concept_categories)} categories. "
            f"Note: Full narrative generation failed due to: {error_message}"
        )

        return NarrativeSummary(
            repo_id=repo_id,
            purpose=purpose,
            capabilities=capabilities,
            components=components,
            how_it_works=how_it_works,
            full_narrative=full_narrative,
        )
