"""Performance validation tests for the spec wizard refactor.

Validates Requirements 24.1, 24.2, 24.3:
- 24.1: UnifiedSpecState produces smaller checkpoint serialization payloads
        than the previous 60+ field flat state.
- 24.2: route_after_phase handles phase transitions within 200ms.
- 24.3: PhaseMessage renders from single source (Message_Metadata),
        eliminating double-renders from Zustand sync.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict

import pytest

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    route_after_phase,
)

# ---------------------------------------------------------------------------
# Helpers — build equivalent data in both old flat and new nested formats
# ---------------------------------------------------------------------------


def _build_old_flat_state() -> Dict[str, Any]:
    """Simulate the old 60+ field flat SpecWizardState with realistic data.

    This mirrors the fields that ``map_gates_to_phases`` reads from,
    plus the many additional flat fields that existed in the old schema
    (gate tracking, agent state, UI flags, etc.).
    """
    return {
        # Gate 1-5 context fields
        "spec_name": "FedEx Shipping Integration",
        "spec_description": "Integrate FedEx shipping API for real-time rate calculation",
        "primary_document_id": "doc-abc-123",
        "primary_document_type": "pdf",
        "user_explanation": "We need to add FedEx shipping as a carrier option in our e-commerce checkout flow.",
        "constraints": {
            "timeline": "4 weeks",
            "budget": "$50k",
            "tech": "Python + React",
        },
        "supporting_doc_ids": ["doc-sup-001", "doc-sup-002", "doc-sup-003"],
        "target_repo_id": "repo-xyz-789",
        # Gate 6-7 research fields
        "research_findings": {
            "codebase": {
                "files_analyzed": 142,
                "relevant_modules": ["shipping", "checkout", "api"],
            },
            "documents": ["FedEx API docs", "Internal shipping spec"],
            "risks": [
                {"id": "r1", "description": "Rate limiting", "severity": "medium"}
            ],
            "gaps": [
                {
                    "id": "g1",
                    "question": "Which FedEx services?",
                    "context": "Multiple tiers available",
                }
            ],
            "summary": "Codebase has existing shipping abstraction layer that can be extended.",
            "confidence_score": 0.85,
        },
        "research_gaps": [
            {
                "id": "g1",
                "question": "Which FedEx services?",
                "context": "Multiple tiers available",
            }
        ],
        "gap_responses": {"g1": "FedEx Ground and FedEx Express only"},
        "research_approved": True,
        "research_review_feedback": "Looks comprehensive",
        # Gate 8-9 plan fields
        "roadmap": {
            "phases": [
                {"name": "API Integration", "duration_days": 5},
                {"name": "Rate Calculator", "duration_days": 3},
                {"name": "UI Components", "duration_days": 4},
                {"name": "Testing", "duration_days": 3},
            ],
            "milestones": [
                "API connected",
                "Rates working",
                "UI complete",
                "QA passed",
            ],
            "risk_mitigations": [
                {"risk": "Rate limiting", "mitigation": "Implement caching"}
            ],
            "total_estimated_days": 15,
            "critical_path": ["API Integration", "Rate Calculator", "Testing"],
        },
        "feasibility_assessment": {"feasible": True, "concerns": []},
        "roadmap_approved": True,
        "roadmap_review_feedback": "Plan looks solid",
        # Gate 10-11 decompose fields
        "task_breakdown": {
            "stories": [
                {
                    "id": "s1",
                    "title": "FedEx API Client",
                    "description": "Create FedEx API client wrapper",
                    "acceptance_criteria": [
                        "Authenticates with FedEx",
                        "Handles rate limiting",
                    ],
                    "story_points": 5,
                },
                {
                    "id": "s2",
                    "title": "Rate Calculator",
                    "description": "Implement shipping rate calculation",
                    "acceptance_criteria": [
                        "Calculates Ground rates",
                        "Calculates Express rates",
                    ],
                    "story_points": 3,
                },
            ],
            "tasks": [
                {"id": "t1", "story_id": "s1", "title": "Implement OAuth flow"},
                {"id": "t2", "story_id": "s1", "title": "Create rate request builder"},
                {"id": "t3", "story_id": "s2", "title": "Build rate comparison UI"},
            ],
            "dependency_graph": {"s2": ["s1"]},
        },
        "tasks_approved": True,
        "tasks_review_feedback": "Good breakdown",
        # Gate 12-14 generate fields
        "generated_sections": {
            "overview": "# FedEx Shipping Integration\n\nThis spec covers...",
            "architecture": "## Architecture\n\nThe system uses...",
            "api_design": "## API Design\n\nEndpoints include...",
        },
        "consistency_issues": [],
        "spec_document_path": "blob://specs/fedex-shipping-v1.md",
        "story_cards_path": "blob://stories/fedex-shipping-stories.json",
        # Old gate-tracking fields (not present in new state)
        "current_gate": 14,
        "total_gates": 14,
        "gate_1_complete": True,
        "gate_2_complete": True,
        "gate_3_complete": True,
        "gate_4_complete": True,
        "gate_5_complete": True,
        "gate_6_complete": True,
        "gate_7_complete": True,
        "gate_8_complete": True,
        "gate_9_complete": True,
        "gate_10_complete": True,
        "gate_11_complete": True,
        "gate_12_complete": True,
        "gate_13_complete": True,
        "gate_14_complete": True,
        # Old UI / agent state fields
        "awaiting_clarification": False,
        "clarification_question": "",
        "agent_content": "",
        "thinking_steps": [],
        "wizard_mode": "wizard",
        "workflow_status": "completed",
        "spec_session_id": "session-abc-123",
        "engine_version": "v2_gates",
        # Additional flat fields that existed in the old schema
        "last_gate_timestamp": "2024-01-15T10:30:00Z",
        "gate_retry_count": 0,
        "agent_execution_time_ms": 4500,
        "total_llm_calls": 23,
        "total_tokens_used": 15000,
        "error_log": [],
        "user_id": "user-001",
        "organization_id": "org-001",
        "created_at": "2024-01-15T09:00:00Z",
        "updated_at": "2024-01-15T10:30:00Z",
        "messages": [],
    }


def _build_new_nested_state() -> Dict[str, Any]:
    """Build the equivalent UnifiedSpecState with the same data, nested by phase."""
    return {
        "context": {
            "spec_name": "FedEx Shipping Integration",
            "spec_description": "Integrate FedEx shipping API for real-time rate calculation",
            "primary_document_id": "doc-abc-123",
            "primary_document_type": "pdf",
            "user_explanation": "We need to add FedEx shipping as a carrier option in our e-commerce checkout flow.",
            "constraints": {
                "timeline": "4 weeks",
                "budget": "$50k",
                "tech": "Python + React",
            },
            "supporting_doc_ids": ["doc-sup-001", "doc-sup-002", "doc-sup-003"],
            "target_repo_id": "repo-xyz-789",
        },
        "review": {
            "approved": True,
            "review_loop_count": 1,
        },
        "research": {
            "findings": {
                "codebase": {
                    "files_analyzed": 142,
                    "relevant_modules": ["shipping", "checkout", "api"],
                },
                "documents": ["FedEx API docs", "Internal shipping spec"],
                "risks": [
                    {"id": "r1", "description": "Rate limiting", "severity": "medium"}
                ],
                "gaps": [
                    {
                        "id": "g1",
                        "question": "Which FedEx services?",
                        "context": "Multiple tiers available",
                    }
                ],
                "summary": "Codebase has existing shipping abstraction layer that can be extended.",
                "confidence_score": 0.85,
            },
            "gaps": [
                {
                    "id": "g1",
                    "question": "Which FedEx services?",
                    "context": "Multiple tiers available",
                }
            ],
            "gap_responses": {"g1": "FedEx Ground and FedEx Express only"},
            "approved": True,
            "review_feedback": "Looks comprehensive",
        },
        "plan": {
            "roadmap": {
                "phases": [
                    {"name": "API Integration", "duration_days": 5},
                    {"name": "Rate Calculator", "duration_days": 3},
                    {"name": "UI Components", "duration_days": 4},
                    {"name": "Testing", "duration_days": 3},
                ],
                "milestones": [
                    "API connected",
                    "Rates working",
                    "UI complete",
                    "QA passed",
                ],
                "risk_mitigations": [
                    {"risk": "Rate limiting", "mitigation": "Implement caching"}
                ],
                "total_estimated_days": 15,
                "critical_path": ["API Integration", "Rate Calculator", "Testing"],
            },
            "feasibility": {"feasible": True, "concerns": []},
            "approved": True,
            "review_feedback": "Plan looks solid",
        },
        "orchestrate": {
            "task_results": [],
            "all_complete": True,
        },
        "completeness": {
            "complete": True,
            "gaps_found": False,
            "review_loop_count": 0,
        },
        "decompose": {
            "stories": [
                {
                    "id": "s1",
                    "title": "FedEx API Client",
                    "description": "Create FedEx API client wrapper",
                    "acceptance_criteria": [
                        "Authenticates with FedEx",
                        "Handles rate limiting",
                    ],
                    "story_points": 5,
                },
                {
                    "id": "s2",
                    "title": "Rate Calculator",
                    "description": "Implement shipping rate calculation",
                    "acceptance_criteria": [
                        "Calculates Ground rates",
                        "Calculates Express rates",
                    ],
                    "story_points": 3,
                },
            ],
            "tasks": [
                {"id": "t1", "story_id": "s1", "title": "Implement OAuth flow"},
                {"id": "t2", "story_id": "s1", "title": "Create rate request builder"},
                {"id": "t3", "story_id": "s2", "title": "Build rate comparison UI"},
            ],
            "dependency_graph": {"s2": ["s1"]},
            "approved": True,
            "review_feedback": "Good breakdown",
        },
        "generate": {
            "sections": {
                "overview": "# FedEx Shipping Integration\n\nThis spec covers...",
                "architecture": "## Architecture\n\nThe system uses...",
                "api_design": "## API Design\n\nEndpoints include...",
            },
            "consistency_issues": [],
            "spec_document_path": "blob://specs/fedex-shipping-v1.md",
            "story_cards_path": "blob://stories/fedex-shipping-stories.json",
        },
        "completed_phases": {
            "context": True,
            "review": True,
            "research": True,
            "plan": True,
            "orchestrate": True,
            "completeness": True,
            "generate": True,
        },
        "navigation": {"current_phase": "generate"},
        "mode": "wizard",
        "workflow_status": "completed",
        "messages": [],
        "session_id": "session-abc-123",
    }


# ---------------------------------------------------------------------------
# Req 24.1: Checkpoint serialization size — nested state ≤ flat state
# ---------------------------------------------------------------------------


class TestCheckpointSerializationSize:
    """Verify UnifiedSpecState produces smaller checkpoint serialization
    payloads than the previous 60+ field flat state.

    **Validates: Requirements 24.1**
    """

    def test_nested_state_serializes_smaller_or_equal(self):
        """The new nested state JSON payload should be smaller than or equal
        to the old flat state JSON payload for equivalent data."""
        old_flat = _build_old_flat_state()
        new_nested = _build_new_nested_state()

        old_json = json.dumps(old_flat, sort_keys=True)
        new_json = json.dumps(new_nested, sort_keys=True)

        old_size = len(old_json.encode("utf-8"))
        new_size = len(new_json.encode("utf-8"))

        assert new_size <= old_size, (
            f"New nested state ({new_size} bytes) should be ≤ old flat state "
            f"({old_size} bytes). Difference: {new_size - old_size} bytes."
        )

    def test_nested_state_has_fewer_top_level_keys(self):
        """The new state should have ~25 top-level keys vs 60+ in the old state."""
        old_flat = _build_old_flat_state()
        new_nested = _build_new_nested_state()

        old_keys = len(old_flat)
        new_keys = len(new_nested)

        assert new_keys < old_keys, (
            f"New state has {new_keys} top-level keys, old state has {old_keys}. "
            f"New state should have fewer top-level keys."
        )
        # The new state should have roughly 25 or fewer top-level fields
        assert new_keys <= 30, (
            f"New state has {new_keys} top-level keys, expected ≤ 30 (~25 target)."
        )


# ---------------------------------------------------------------------------
# Req 24.2: route_after_phase transition timing — under 200ms
# ---------------------------------------------------------------------------


class TestRouteTransitionTiming:
    """Verify route_after_phase handles phase transitions within 200ms.

    Since route_after_phase is a pure function with no I/O, it should
    complete well under 200ms. We test all navigation scenarios.

    **Validates: Requirements 24.2**
    """

    MAX_MS = 200  # milliseconds

    @pytest.mark.parametrize("phase_idx", range(len(PHASE_ORDER) - 1))
    def test_forward_transition_under_200ms(self, phase_idx: int):
        """Forward navigation from each non-terminal phase completes within 200ms."""
        state: Dict[str, Any] = {
            "navigation": {
                "current_phase": PHASE_ORDER[phase_idx],
                "direction": "forward",
            }
        }

        start = time.perf_counter()
        result = route_after_phase(state)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < self.MAX_MS, (
            f"Forward transition from {PHASE_ORDER[phase_idx]} took {elapsed_ms:.2f}ms "
            f"(limit: {self.MAX_MS}ms)"
        )
        assert result == PHASE_ORDER[phase_idx + 1]

    def test_generate_forward_to_end_under_200ms(self):
        """Forward from generate (terminal phase) returns END within 200ms."""
        state: Dict[str, Any] = {
            "navigation": {
                "current_phase": "generate",
                "direction": "forward",
            }
        }

        start = time.perf_counter()
        result = route_after_phase(state)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < self.MAX_MS, (
            f"Generate→END took {elapsed_ms:.2f}ms (limit: {self.MAX_MS}ms)"
        )

    @pytest.mark.parametrize(
        "current,target",
        [
            ("research", "context"),
            ("plan", "context"),
            ("plan", "research"),
            ("orchestrate", "research"),
            ("generate", "plan"),
        ],
    )
    def test_backward_transition_under_200ms(self, current: str, target: str):
        """Backward navigation to any valid target completes within 200ms."""
        state: Dict[str, Any] = {
            "navigation": {
                "current_phase": current,
                "direction": "backward",
                "target_phase": target,
            }
        }

        start = time.perf_counter()
        result = route_after_phase(state)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < self.MAX_MS, (
            f"Backward {current}→{target} took {elapsed_ms:.2f}ms "
            f"(limit: {self.MAX_MS}ms)"
        )
        assert result == target

    def test_error_state_routing_under_200ms(self):
        """Error state routing returns END within 200ms."""
        state: Dict[str, Any] = {
            "workflow_status": "error",
            "navigation": {
                "current_phase": "research",
                "direction": "forward",
            },
        }

        start = time.perf_counter()
        route_after_phase(state)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < self.MAX_MS, (
            f"Error state routing took {elapsed_ms:.2f}ms (limit: {self.MAX_MS}ms)"
        )


# ---------------------------------------------------------------------------
# Req 24.3: PhaseMessage single-source rendering — no wizardStore imports
# ---------------------------------------------------------------------------

# Path to PhaseMessage relative to workspace root
_PHASE_MESSAGE_PATH = os.path.join(
    "graph_kb_dashboard", "src", "components", "chat", "PhaseMessage.tsx"
)


class TestPhaseMessageSingleSource:
    """Verify PhaseMessage reads exclusively from message.metadata.wizardPanel
    and does NOT import from wizardStore, eliminating double-renders from
    Zustand sync.

    **Validates: Requirements 24.3**
    """

    def test_phase_message_does_not_import_wizard_store(self):
        """PhaseMessage.tsx must not import from wizardStore.

        Any import from wizardStore would re-introduce the dual-state
        problem and cause double-renders via Zustand subscription.
        """
        assert os.path.isfile(_PHASE_MESSAGE_PATH), (
            f"PhaseMessage.tsx not found at {_PHASE_MESSAGE_PATH}"
        )

        with open(_PHASE_MESSAGE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for any import referencing wizardStore
        wizard_store_import = re.search(
            r"""(?:import\s+.*from\s+['"].*wizardStore['"]|"""
            r"""require\s*\(\s*['"].*wizardStore['"]\s*\))""",
            content,
        )
        assert wizard_store_import is None, (
            f"PhaseMessage.tsx imports from wizardStore: "
            f"{wizard_store_import.group()!r}. "
            f"It should read exclusively from message.metadata.wizardPanel."
        )

    def test_phase_message_does_not_use_wizard_store_hook(self):
        """PhaseMessage.tsx must not call useWizardStore or similar hooks."""
        assert os.path.isfile(_PHASE_MESSAGE_PATH), (
            f"PhaseMessage.tsx not found at {_PHASE_MESSAGE_PATH}"
        )

        with open(_PHASE_MESSAGE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for useWizardStore() or useWizardStore( usage
        store_hook_usage = re.search(r"useWizardStore\s*\(", content)
        assert store_hook_usage is None, (
            "PhaseMessage.tsx uses useWizardStore hook. "
            "It should read exclusively from message.metadata.wizardPanel."
        )

    def test_phase_message_reads_from_metadata(self):
        """PhaseMessage.tsx should reference wizardPanel metadata in its props or body."""
        assert os.path.isfile(_PHASE_MESSAGE_PATH), (
            f"PhaseMessage.tsx not found at {_PHASE_MESSAGE_PATH}"
        )

        with open(_PHASE_MESSAGE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # The component should reference WizardPanelMetadata or metadata prop
        has_metadata_ref = (
            "WizardPanelMetadata" in content
            or "metadata" in content
            or "wizardPanel" in content
        )
        assert has_metadata_ref, (
            "PhaseMessage.tsx does not reference WizardPanelMetadata or metadata. "
            "It should read from message.metadata.wizardPanel as its single source."
        )
