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
from graph_kb_api.flows.v3.state import UnifiedSpecState

import json
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Optional

from langchain.messages import AIMessage

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
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

        sections = task.get("sections", {})
        template = task.get("template", "")

        try:
            # Run assembly
            result: AssemblyResult = await self._assemble_document(sections, template, workflow_context)

            return {
                "output": self._serialize_result(result),
                "summary": result.summary,
                "confidence_score": result.flow_score,
            }

        except Exception as e:
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
    ) -> AssemblyResult:
        """Assemble document using LLM."""
        llm: LLMService = workflow_context.require_llm

        prompt = self._build_assembly_prompt(sections, template)

        try:
            response: AIMessage = await llm.ainvoke(prompt)
            raw_content = response.content if hasattr(response, "content") else str(response)
            content: str = raw_content if isinstance(raw_content, str) else str(raw_content)
            return self._parse_llm_response(content, sections)
        except Exception as e:
            logger.error(f"LLM assembly failed: {e}")
            raise RuntimeError(f"DocumentAssemblyAgent LLM call failed: {e}") from e

    def _build_assembly_prompt(
        self,
        sections: Dict[str, Any],
        template: str,
    ) -> str:
        """Build the assembly prompt."""
        sections_json = json.dumps(sections, indent=2, default=str)

        template_section = f"\n\n## Template to Use\n```\n{template}\n```" if template else ""

        return f"""{_SYSTEM_PROMPT}

## Sections to Assemble
```json
{sections_json}
```
{template_section}

Assemble these sections into a coherent document with smooth transitions.
Return your result as JSON."""

    def _parse_llm_response(
        self,
        content: str,
        sections: Dict[str, Any],
    ) -> AssemblyResult:
        """Parse LLM response into AssemblyResult."""
        import re

        try:
            # Try to extract JSON
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```\s*$", "", cleaned)

            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("Response is not a JSON object")

            return AssemblyResult(
                assembled_document=str(parsed.get("assembled_document", "")),
                sections_included=list(parsed.get("sections_included", [])),
                transitions_generated=list(parsed.get("transitions_generated", [])),
                flow_score=float(parsed.get("flow_score", 0.5)),
                summary=str(parsed.get("summary", "Assembly complete")),
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise RuntimeError(f"DocumentAssemblyAgent failed to parse LLM response: {e}") from e

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
