"""
DocumentAssemblyAgent - LLM-powered document assembly.

Assembles final documents from sections:
- Intelligent section ordering
- Smooth transitions between sections
- Document flow optimization
- Narrative coherence

Used by AssembleNode in the plan workflow assembly phase.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Optional

from langchain.messages import AIMessage

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.flows.v3.state.workflow_state import GenerateData  # noqa: F401

logger = logging.getLogger(__name__)


# ── Data Classes ─────────────────────────────────────────────────────────


@dataclass
class Section:
    """Represents a document section."""

    id: str
    title: str
    content: str
    order: int
    dependencies: List[str] = dc_field(default_factory=list)


@dataclass
class AssemblyResult:
    """Complete assembly result."""

    assembled_document: str
    sections_included: List[str]
    transitions_generated: List[str]
    flow_score: float  # 0.0 - 1.0
    summary: str


# ── System Prompt (Hermes persona) ────────────────────────────────────────

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("document_assembly")


class DocumentAssemblyAgent(BaseAgent):
    """LLM-powered agent for assembling documents from sections.

    Assembles sections into coherent documents with smooth transitions
    and optimized flow.
    """

    def __init__(self, tools: Optional[List[Any]] = None):
        self._tools = tools or []

    @property
    def capability(self) -> AgentCapability:
        return AgentCapability(
            agent_type="document_assembly",
            supported_tasks=[
                "document_assembly",
                "section_ordering",
                "transition_generation",
                "flow_optimization",
                "template_rendering",
            ],
            required_tools=[],
            optional_tools=[],
            description=("LLM-powered document assembly. Orders sections, generates transitions, optimizes flow."),
            system_prompt=_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute document assembly.

        Args:
            task: Contains 'sections' dict and optional 'template'
            state: Current workflow state
            workflow_context: Application context with LLM

        Returns:
            Dict with assembled document and metadata
        """
        assert workflow_context is not None, "DocumentAssemblyAgent requires a WorkflowContext"

        ctx = task.get("context", {}) if isinstance(task.get("context"), dict) else {}
        sections = ctx.get("sections", task.get("sections", {}))
        template = ctx.get("template", task.get("template", ""))
        spec_name = ctx.get("spec_name", "")
        user_explanation = ctx.get("user_explanation", "")

        try:
            # Run assembly
            result: AssemblyResult = await self._assemble_document(
                sections, template, workflow_context,
                spec_name=spec_name, user_explanation=user_explanation,
            )

            return {
                "output": self._serialize_result(result),
                "summary": result.summary,
                "confidence_score": result.flow_score,
            }

        except Exception as e:
            # Re-raise quota exhaustion so the node-level handler can emit
            # a proper error to the UI instead of silently degrading
            from graph_kb_api.core.llm import LLMQuotaExhaustedError
            if isinstance(e, LLMQuotaExhaustedError) or (
                isinstance(e.__cause__, LLMQuotaExhaustedError) if e.__cause__ else False
            ):
                raise

            logger.error(f"DocumentAssemblyAgent failed: {e}", exc_info=True)
            fallback_doc = self._fallback_assembly(sections, template)
            section_ids = list(sections.keys()) if isinstance(sections, dict) else []
            return {
                "error": str(e),
                "output": {
                    "assembled_document": fallback_doc,
                    "sections_included": section_ids,
                    "transitions_generated": [],
                    "flow_score": 0.3,
                },
                "summary": f"Assembly failed, used fallback: {e}",
            }

    async def _assemble_document(
        self,
        sections: Dict[str, Any],
        template: str,
        workflow_context: WorkflowContext,
        *,
        spec_name: str = "",
        user_explanation: str = "",
    ) -> AssemblyResult:
        """Assemble document using LLM."""
        llm: LLMService = workflow_context.require_llm

        prompt = self._build_assembly_prompt(
            sections, template, spec_name=spec_name, user_explanation=user_explanation,
        )

        try:
            response: AIMessage = await llm.ainvoke(prompt)
            raw_content = response.content if hasattr(response, "content") else str(response)
            content: str = raw_content if isinstance(raw_content, str) else str(raw_content)
            return self._parse_llm_response(content, sections)
        except Exception as e:
            # Let quota errors propagate without wrapping
            from graph_kb_api.core.llm import LLMQuotaExhaustedError
            if isinstance(e, LLMQuotaExhaustedError):
                raise
            logger.error(f"LLM assembly failed: {e}")
            raise RuntimeError(f"DocumentAssemblyAgent LLM call failed: {e}") from e

    def _build_assembly_prompt(
        self,
        sections: Dict[str, Any],
        template: str,
        *,
        spec_name: str = "",
        user_explanation: str = "",
    ) -> str:
        """Build the assembly prompt with sections as markdown."""
        section_parts: list[str] = []
        for name, content in sections.items():
            text = str(content) if not isinstance(content, str) else content
            section_parts.append(f"### Section: {name}\n\n{text}")

        sections_text = "\n\n---\n\n".join(section_parts)
        template_section = f"\n\n## Template to Use\n```\n{template}\n```" if template else ""

        # Build document context block so the LLM knows what it's assembling
        context_lines: list[str] = []
        if spec_name:
            context_lines.append(f"**Document title:** {spec_name}")
        if user_explanation:
            context_lines.append(f"**Purpose:** {user_explanation}")
        context_block = "\n".join(context_lines)
        context_section = f"\n\n## Document Context\n\n{context_block}\n" if context_lines else ""

        return f"""{_SYSTEM_PROMPT}
{context_section}
## Input Sections

The following sections were independently researched and drafted. Assemble them
into a single, coherent specification document. The sections are provided in
their intended reading order.

{sections_text}
{template_section}

## Reminders

- The document title should be: {spec_name or 'derive from the content'}.
- Preserve all code blocks, tables, mermaid diagrams, and interface definitions exactly.
- Strip YAML frontmatter, task IDs, status fields, and workflow metadata.
- Merge overlapping content; eliminate redundancy without losing information.
- Add concrete transitions between sections — reference specific concepts, not generic filler.
- Return ONLY raw markdown. No JSON wrapper. No code fences around the document."""

    def _parse_llm_response(
        self,
        content: str,
        sections: Dict[str, Any],
    ) -> AssemblyResult:
        """Parse LLM response — expects raw markdown, not JSON."""
        cleaned = content.strip()

        # Strip outer code fences if the LLM wrapped the output
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        # Handle case where LLM returned JSON instead of raw markdown
        cleaned = self._unwrap_json_if_needed(cleaned)

        if not cleaned or len(cleaned) < 50:
            raise RuntimeError("DocumentAssemblyAgent returned empty or trivial content")

        section_names = list(sections.keys()) if isinstance(sections, dict) else []
        return AssemblyResult(
            assembled_document=cleaned,
            sections_included=section_names,
            transitions_generated=[],
            flow_score=0.8,
            summary=f"Assembled {len(section_names)} sections into cohesive document",
        )

    @staticmethod
    def _unwrap_json_if_needed(content: str) -> str:
        """Extract markdown from JSON wrapper if the LLM returned JSON instead of raw markdown.

        Some LLMs wrap the assembled document in a JSON object like:
        {"assembled_document": "# Title...", "sections_included": [...], ...}

        This method detects that pattern and extracts just the markdown content.
        """
        if not content.startswith("{"):
            return content
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "assembled_document" in parsed:
                doc = parsed["assembled_document"]
                if isinstance(doc, str) and len(doc) > 50:
                    logger.info("_unwrap_json_if_needed: extracted assembled_document from JSON wrapper")
                    return doc
        except (json.JSONDecodeError, ValueError):
            pass
        return content

    def _fallback_assembly_result(
        self,
        sections: Dict[str, Any],
        template: str,
    ) -> AssemblyResult:
        """Create fallback assembly result."""
        assembled = self._fallback_assembly(sections, template)
        section_ids = list(sections.keys()) if isinstance(sections, dict) else []

        return AssemblyResult(
            assembled_document=assembled,
            sections_included=section_ids,
            transitions_generated=[],
            flow_score=0.4,
            summary="Basic assembly (LLM unavailable)",
        )

    def _fallback_assembly(
        self,
        sections: Dict[str, Any],
        template: str,
    ) -> str:
        """Simple fallback assembly without LLM."""
        if not sections:
            return template or ""

        # If template provided, try to fill it
        if template:
            try:
                return template.format(**sections)
            except (KeyError, ValueError):
                pass

        # Otherwise concatenate sections
        parts = []
        for section_id, content in sections.items():
            if isinstance(content, str):
                parts.append(f"## {section_id.replace('_', ' ').title()}\n\n{content}")
            elif isinstance(content, dict):
                parts.append(f"## {section_id.replace('_', ' ').title()}\n\n{json.dumps(content, indent=2)}")

        return "\n\n".join(parts)

    def _serialize_result(self, result: AssemblyResult) -> Dict[str, Any]:
        return {
            "assembled_document": result.assembled_document,
            "sections_included": result.sections_included,
            "transitions_generated": result.transitions_generated,
            "flow_score": result.flow_score,
            "summary": result.summary,
        }


# ── Register with AgentRegistry ─────────────────────────────────────

from graph_kb_api.flows.v3.agents.registry import AgentRegistry  # noqa: E402

AgentRegistry.register(DocumentAssemblyAgent)
