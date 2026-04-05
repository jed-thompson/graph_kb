"""
Consistency checker agent for the multi-agent feature spec workflow.

Runs periodically (every N completed sections) to verify cross-section
consistency. Checks that data model references match definitions across
sections, naming conventions are consistent, and detects contradictions.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Mapping, Set, Tuple

from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models import AgentResult, AgentTask
from graph_kb_api.flows.v3.models.types import (
    ConsistencyIssue,
    consistency_checker_capability,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("consistency_checker")

# ---------------------------------------------------------------------------
# Heuristic patterns for consistency checking
# ---------------------------------------------------------------------------

# Pattern to find data model / class / type references
_MODEL_DEF_PATTERN = re.compile(r"(?:class|model|type|interface|struct)\s+(\w+)", re.IGNORECASE)

# Pattern to find field/attribute references like `ModelName.field_name`
_FIELD_REF_PATTERN = re.compile(r"\b([A-Z]\w+)\.(\w+)\b")

# Pattern to find endpoint references like `GET /api/...` or `POST /api/...`
_ENDPOINT_PATTERN = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", re.IGNORECASE)

# Naming convention patterns
_SNAKE_CASE: re.Pattern[str] = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_CAMEL_CASE: re.Pattern[str] = re.compile(r"\b[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b")
_PASCAL_CASE: re.Pattern[str] = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")


def _extract_model_definitions(content: str) -> Set[str]:
    """Extract model/class/type names defined in a section."""
    return {m.group(1) for m in _MODEL_DEF_PATTERN.finditer(content)}


def _extract_model_references(content: str) -> List[Tuple[str, str]]:
    """Extract ModelName.field references from a section."""
    return [(m.group(1), m.group(2)) for m in _FIELD_REF_PATTERN.finditer(content)]


def _extract_endpoints(content: str) -> List[Tuple[str, str]]:
    """Extract HTTP method + path pairs from a section."""
    return [(m.group(1).upper(), m.group(2)) for m in _ENDPOINT_PATTERN.finditer(content)]


def _detect_naming_style(content: str) -> Dict[str, int]:
    """Count occurrences of different naming conventions."""
    return {
        "snake_case": len(_SNAKE_CASE.findall(content)),
        "camelCase": len(_CAMEL_CASE.findall(content)),
        "PascalCase": len(_PASCAL_CASE.findall(content)),
    }


def check_data_model_consistency(
    completed_sections: Dict[str, str],
) -> List[ConsistencyIssue]:
    """Check that data model references match definitions across sections.

    Finds all model definitions across sections, then checks that any
    ``ModelName.field`` reference refers to a model that is actually defined.
    """
    issues: List[ConsistencyIssue] = []

    # Collect all model definitions across all sections
    all_definitions: Dict[str, str] = {}  # model_name -> defining section_id
    for section_id, content in completed_sections.items():
        for model_name in _extract_model_definitions(content):
            all_definitions[model_name] = section_id

    # Check references in each section
    for section_id, content in completed_sections.items():
        refs = _extract_model_references(content)
        for model_name, field_name in refs:
            if model_name not in all_definitions:
                issues.append(
                    ConsistencyIssue(
                        issue_id=f"dm_{uuid.uuid4().hex[:8]}",
                        issue_type="data_model_mismatch",
                        description=(
                            f"Section '{section_id}' references "
                            f"'{model_name}.{field_name}' but '{model_name}' "
                            f"is not defined in any completed section."
                        ),
                        affected_sections=[section_id],
                        severity="error",
                        suggested_fix=(
                            f"Define '{model_name}' in the data models section "
                            f"or correct the reference in '{section_id}'."
                        ),
                    )
                )

    return issues


def check_naming_consistency(
    completed_sections: Dict[str, str],
) -> List[ConsistencyIssue]:
    """Check that naming conventions are consistent across sections.

    If one section predominantly uses snake_case and another uses camelCase,
    flag a warning.
    """
    issues: List[ConsistencyIssue] = []

    section_styles: Dict[str, str] = {}
    for section_id, content in completed_sections.items():
        counts = _detect_naming_style(content)
        # Determine dominant style (ignore PascalCase as it's used for types)
        snake = counts["snake_case"]
        camel = counts["camelCase"]
        if snake > 0 or camel > 0:
            section_styles[section_id] = "snake_case" if snake >= camel else "camelCase"

    # Check for mixed styles
    styles_used = set(section_styles.values())
    if len(styles_used) > 1:
        affected = list(section_styles.keys())
        issues.append(
            ConsistencyIssue(
                issue_id=f"nc_{uuid.uuid4().hex[:8]}",
                issue_type="naming_inconsistency",
                description=(
                    f"Mixed naming conventions detected across sections: "
                    f"{dict(section_styles)}. Consider standardizing."
                ),
                affected_sections=affected,
                severity="warning",
                suggested_fix="Standardize on a single naming convention across all sections.",
            )
        )

    return issues


def check_contradictions(
    completed_sections: Dict[str, str],
) -> List[ConsistencyIssue]:
    """Detect contradictions between sections.

    Checks for conflicting endpoint definitions (same path, different methods
    or descriptions in different sections).
    """
    issues: List[ConsistencyIssue] = []

    # Collect endpoints per section
    endpoint_map: Dict[str, List[str]] = {}  # "METHOD /path" -> [section_ids]
    for section_id, content in completed_sections.items():
        endpoints = _extract_endpoints(content)
        for method, path in endpoints:
            key = f"{method} {path}"
            endpoint_map.setdefault(key, []).append(section_id)

    # Flag endpoints defined in multiple sections (potential contradiction)
    for endpoint_key, section_ids in endpoint_map.items():
        if len(section_ids) > 1:
            unique_sections = list(set(section_ids))
            if len(unique_sections) > 1:
                issues.append(
                    ConsistencyIssue(
                        issue_id=f"ct_{uuid.uuid4().hex[:8]}",
                        issue_type="contradiction",
                        description=(
                            f"Endpoint '{endpoint_key}' is defined in multiple "
                            f"sections: {unique_sections}. This may indicate "
                            f"conflicting specifications."
                        ),
                        affected_sections=unique_sections,
                        severity="warning",
                        suggested_fix=(f"Consolidate the definition of '{endpoint_key}' into a single section."),
                    )
                )

    return issues


class ConsistencyCheckerAgent(BaseAgent):
    """Periodically checks cross-section consistency.

    Extends BaseAgent with AgentCapability for consistency checking.
    Verifies data model references match definitions, checks naming
    conventions, and detects contradictions between sections.

    Returns:
        - consistency_issues: List[ConsistencyIssue]
        - is_consistent: bool (True if no error-severity issues)
        - affected_sections: List[str] — section_ids needing correction
    """

    def __init__(self) -> None:
        pass

    @property
    def capability(self) -> AgentCapability:
        return consistency_checker_capability(system_prompt=_SYSTEM_PROMPT)

    async def execute(
        self,
        task: AgentTask,
        state: Mapping[str, Any],
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Check consistency across all completed sections.

        Runs three checks:
          1. Data model reference consistency
          2. Naming convention consistency
          3. Contradiction detection

        Error-severity issues block progress; warning-severity issues are
        noted but do not block.
        """
        completed_sections: Dict[str, str] = dict(state.get("completed_sections", {}) or {})

        all_issues: List[ConsistencyIssue] = []

        # Run all consistency checks
        all_issues.extend(check_data_model_consistency(completed_sections))
        all_issues.extend(check_naming_consistency(completed_sections))
        all_issues.extend(check_contradictions(completed_sections))

        # Determine overall consistency — only error-severity issues block
        error_issues: list[ConsistencyIssue] = [i for i in all_issues if i.severity == "error"]
        is_consistent: bool = len(error_issues) == 0

        # Collect affected sections (from error-severity issues only for routing)
        affected_sections: List[str] = []
        seen: set = set()
        for issue in error_issues:
            for sid in issue.affected_sections:
                if sid not in seen:
                    affected_sections.append(sid)
                    seen.add(sid)

        # Convert issues to dicts for state storage
        issues_as_dicts = [issue.to_dict() for issue in all_issues]

        return AgentResult(
            output=json.dumps(
                {
                    "consistency_issues": issues_as_dicts,
                    "is_consistent": is_consistent,
                    "affected_sections": affected_sections,
                    "trigger_consistency_check": False,  # Reset the trigger
                }
            ),
            tokens=0,  # No LLM used
            agent_type="consistency_checker",
        )
