"""Integration tests: Subgraph transition context → research with state pruning.

Simulates context subgraph output, runs PruneAfterResearchNode on research state,
verifies ArtifactRefs preserved, inline data cleared, summary fields preserved,
and pruned state is valid for the research subgraph.

Also tests PruneAfterOrchestrateNode between orchestrate and assembly subgraphs.

**Validates: Requirements 17.2, 18.1, 18.2, 18.3**
"""

import pytest

from graph_kb_api.flows.v3.models.node_models import NodeExecutionStatus
from graph_kb_api.flows.v3.nodes.plan_nodes import (
    PRESERVE_AFTER_ORCHESTRATE,
    PRESERVE_AFTER_RESEARCH,
    PruneAfterOrchestrateNode,
    PruneAfterResearchNode,
)
from graph_kb_api.flows.v3.state.plan_state import ArtifactRef

# ---------------------------------------------------------------------------
# Helpers — build realistic state snapshots
# ---------------------------------------------------------------------------


def _make_artifact_ref(namespace: str, name: str) -> ArtifactRef:
    """Create a realistic ArtifactRef for testing."""
    return ArtifactRef(
        key=f"specs/test-session/{namespace}/{name}",
        content_hash="a1b2c3d4e5f6" + "0" * 52,  # 64-char hex
        size_bytes=4096,
        created_at="2024-06-01T12:00:00Z",
        summary=f"Summary for {namespace}/{name}.",
    )


def _build_post_research_state() -> dict:
    """Build state simulating context subgraph completion + research output.

    Contains:
    - ArtifactRefs for research results (should be preserved after prune)
    - Inline data arrays: web_results, vector_results, graph_results (cleared)
    - Summary fields: findings, approved, review_feedback, gaps (preserved)
    """
    return {
        "artifacts": {
            "research.web_results": _make_artifact_ref("research", "web_results.json"),
            "research.vector_results": _make_artifact_ref(
                "research", "vector_results.json"
            ),
            "research.graph_results": _make_artifact_ref(
                "research", "graph_results.json"
            ),
            "context.analysis": _make_artifact_ref("context", "analysis.json"),
        },
        "research": {
            # Inline data — should be pruned (Req 18.2)
            "web_results": [{"url": "https://example.com", "content": "x" * 500}],
            "vector_results": [{"chunk": "embedding data", "score": 0.95}],
            "graph_results": [
                {"node": "AuthService", "relations": ["uses", "depends"]}
            ],
            # Summary / routing fields — should be preserved (Req 18.3)
            "findings": {"summary": "Found 3 relevant patterns", "confidence": 0.87},
            "approved": True,
            "review_feedback": "Research is comprehensive",
            "gaps": [],
            "targets": {"repos": ["graph-kb"], "urls": ["https://docs.example.com"]},
        },
        "budget": {
            "max_llm_calls": 200,
            "remaining_llm_calls": 180,
            "max_tokens": 500000,
            "tokens_used": 12000,
            "max_wall_clock_s": 1800,
            "started_at": "2024-06-01T12:00:00Z",
        },
        "session_id": "test-session",
    }


def _build_post_orchestrate_state() -> dict:
    """Build state simulating orchestrate subgraph completion.

    Contains:
    - ArtifactRefs for task drafts (preserved after prune)
    - Iteration data: critique_history, iteration_count, current_task_context (cleared)
    - Summary fields: task_results, all_complete, critique_feedback (preserved)
    """
    return {
        "artifacts": {
            "orchestrate.task_t1.draft": _make_artifact_ref(
                "orchestrate", "tasks/t1/draft.md"
            ),
            "orchestrate.task_t2.draft": _make_artifact_ref(
                "orchestrate", "tasks/t2/draft.md"
            ),
            "research.web_results": _make_artifact_ref("research", "web_results.json"),
        },
        "orchestrate": {
            # Iteration data — should be pruned (Req 18.2)
            "critique_history": [
                {"round": 1, "verdict": "revise", "feedback": "Needs more detail"},
                {"round": 2, "verdict": "approve", "feedback": "Looks good"},
            ],
            "iteration_count": 2,
            "current_task_context": {"task_id": "t2", "agent": "backend"},
            # Summary / output fields — should be preserved (Req 18.3)
            "task_results": [
                {
                    "id": "t1",
                    "status": "done",
                    "output_ref": "orchestrate.task_t1.draft",
                },
                {
                    "id": "t2",
                    "status": "done",
                    "output_ref": "orchestrate.task_t2.draft",
                },
            ],
            "all_complete": True,
            "critique_feedback": "All tasks meet quality bar",
            "task_iterations": {
                "t1": [{"iteration": 1, "approved": True}],
                "t2": [
                    {"iteration": 1, "approved": False},
                    {"iteration": 2, "approved": True},
                ],
            },
        },
        "budget": {
            "max_llm_calls": 200,
            "remaining_llm_calls": 50,
            "max_tokens": 500000,
            "tokens_used": 350000,
            "max_wall_clock_s": 1800,
            "started_at": "2024-06-01T12:00:00Z",
        },
        "session_id": "test-session",
    }


# ---------------------------------------------------------------------------
# Tests: Context → PruneAfterResearch → Research subgraph transition
# ---------------------------------------------------------------------------


class TestContextToResearchTransition:
    """Integration: context subgraph output → prune → research subgraph input."""

    @pytest.fixture
    def prune_node(self):
        return PruneAfterResearchNode()

    @pytest.mark.asyncio
    async def test_artifact_refs_preserved_after_prune(self, prune_node):
        """Req 18.1: All ArtifactRef entries in state.artifacts must survive pruning."""
        state = _build_post_research_state()
        original_artifacts = dict(state["artifacts"])

        result = await prune_node._execute_step(state, {})

        assert result.status == NodeExecutionStatus.SUCCESS
        # Prune node only returns research key — artifacts untouched at top level
        assert "artifacts" not in result.output
        # Original artifacts dict is unchanged
        assert state["artifacts"] == original_artifacts

    @pytest.mark.asyncio
    async def test_inline_data_cleared_after_prune(self, prune_node):
        """Req 18.2: web_results, vector_results, graph_results must be cleared."""
        state = _build_post_research_state()

        result = await prune_node._execute_step(state, {})
        pruned_research = result.output["research"]

        assert "web_results" not in pruned_research
        assert "vector_results" not in pruned_research
        assert "graph_results" not in pruned_research

    @pytest.mark.asyncio
    async def test_summary_fields_preserved_after_prune(self, prune_node):
        """Req 11.1: Allowlisted fields in PRESERVE_AFTER_RESEARCH are preserved."""
        state = _build_post_research_state()

        result = await prune_node._execute_step(state, {})
        pruned_research = result.output["research"]

        assert pruned_research["findings"] == {
            "summary": "Found 3 relevant patterns",
            "confidence": 0.87,
        }
        assert pruned_research["approved"] is True
        assert pruned_research["review_feedback"] == "Research is comprehensive"
        # gaps and targets are NOT in PRESERVE_AFTER_RESEARCH — pruned by allowlist
        assert "gaps" not in pruned_research
        assert "targets" not in pruned_research

    @pytest.mark.asyncio
    async def test_pruned_state_valid_for_downstream(self, prune_node):
        """Req 17.2: Pruned state is valid input for the next subgraph.

        After pruning, the research dict should contain only summary/routing
        fields — no large inline arrays. Artifacts dict still has all
        ArtifactRef pointers so downstream nodes can hydrate on demand.
        """
        state = _build_post_research_state()

        result = await prune_node._execute_step(state, {})
        pruned_research = result.output["research"]

        # Downstream planning subgraph needs: findings, approved, targets
        assert "findings" in pruned_research
        assert "approved" in pruned_research

        # No large inline data should remain
        for key in pruned_research:
            assert key in PRESERVE_AFTER_RESEARCH, (
                f"Non-preserved key '{key}' survived pruning"
            )

    @pytest.mark.asyncio
    async def test_merged_state_has_artifacts_and_pruned_research(self, prune_node):
        """Simulate the state merge that LangGraph performs after prune node."""
        state = _build_post_research_state()
        original_artifacts = dict(state["artifacts"])

        result = await prune_node._execute_step(state, {})

        # Simulate LangGraph merge: prune output replaces research via operator.or_
        merged = {**state}
        merged["research"] = result.output["research"]

        # Artifacts preserved at top level
        assert merged["artifacts"] == original_artifacts
        # Research pruned
        assert "web_results" not in merged["research"]
        assert merged["research"]["approved"] is True
        # Budget unchanged
        assert merged["budget"]["remaining_llm_calls"] == 180


# ---------------------------------------------------------------------------
# Tests: Orchestrate → PruneAfterOrchestrate → Assembly subgraph transition
# ---------------------------------------------------------------------------


class TestOrchestrateToAssemblyTransition:
    """Integration: orchestrate subgraph output → prune → assembly subgraph input."""

    @pytest.fixture
    def prune_node(self):
        return PruneAfterOrchestrateNode()

    @pytest.mark.asyncio
    async def test_artifact_refs_preserved_after_prune(self, prune_node):
        """Req 18.1: All ArtifactRef entries must survive pruning."""
        state = _build_post_orchestrate_state()
        original_artifacts = dict(state["artifacts"])

        result = await prune_node._execute_step(state, {})

        assert result.status == NodeExecutionStatus.SUCCESS
        assert "artifacts" not in result.output
        assert state["artifacts"] == original_artifacts

    @pytest.mark.asyncio
    async def test_iteration_data_cleared_after_prune(self, prune_node):
        """Req 18.2: critique_history, iteration_count, current_task_context cleared."""
        state = _build_post_orchestrate_state()

        result = await prune_node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        assert "critique_history" not in pruned
        assert "iteration_count" not in pruned
        assert "current_task_context" not in pruned

    @pytest.mark.asyncio
    async def test_summary_fields_preserved_after_prune(self, prune_node):
        """Req 11.1: Allowlisted fields in PRESERVE_AFTER_ORCHESTRATE are preserved."""
        state = _build_post_orchestrate_state()

        result = await prune_node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        assert len(pruned["task_results"]) == 2
        assert pruned["all_complete"] is True
        # critique_feedback and task_iterations are NOT in PRESERVE_AFTER_ORCHESTRATE — pruned
        assert "critique_feedback" not in pruned
        assert "task_iterations" not in pruned

    @pytest.mark.asyncio
    async def test_pruned_state_valid_for_assembly(self, prune_node):
        """Req 17.2: Pruned state is valid input for assembly subgraph."""
        state = _build_post_orchestrate_state()

        result = await prune_node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        # Assembly needs task results to know what was produced
        assert "task_results" in pruned
        # Only allowlisted keys should survive
        for key in pruned:
            assert key in PRESERVE_AFTER_ORCHESTRATE, (
                f"Non-preserved key '{key}' survived pruning"
            )

    @pytest.mark.asyncio
    async def test_merged_state_has_artifacts_and_pruned_orchestrate(self, prune_node):
        """Simulate LangGraph merge after orchestrate prune."""
        state = _build_post_orchestrate_state()
        original_artifacts = dict(state["artifacts"])

        result = await prune_node._execute_step(state, {})

        merged = {**state}
        merged["orchestrate"] = result.output["orchestrate"]

        assert merged["artifacts"] == original_artifacts
        assert "critique_history" not in merged["orchestrate"]
        assert merged["orchestrate"]["all_complete"] is True
        assert merged["budget"]["remaining_llm_calls"] == 50
        # Allowlist: only preserved keys survive
        assert "critique_feedback" not in merged["orchestrate"]


# ---------------------------------------------------------------------------
# Tests: Cross-cutting prune safety
# ---------------------------------------------------------------------------


class TestPruneSafetyCrossCutting:
    """Both prune nodes preserve ArtifactRefs and don't mutate input state."""

    @pytest.mark.asyncio
    async def test_research_prune_does_not_mutate_input_state(self):
        """Prune node must not mutate the input state dict."""
        node = PruneAfterResearchNode()
        state = _build_post_research_state()
        original_research = dict(state["research"])

        await node._execute_step(state, {})

        assert state["research"] == original_research
        assert "web_results" in state["research"]

    @pytest.mark.asyncio
    async def test_orchestrate_prune_does_not_mutate_input_state(self):
        """Prune node must not mutate the input state dict."""
        node = PruneAfterOrchestrateNode()
        state = _build_post_orchestrate_state()
        original_orchestrate = dict(state["orchestrate"])

        await node._execute_step(state, {})

        assert state["orchestrate"] == original_orchestrate
        assert "critique_history" in state["orchestrate"]

    @pytest.mark.asyncio
    async def test_both_prune_nodes_return_success(self):
        """Both prune nodes should always return SUCCESS status."""
        r1 = await PruneAfterResearchNode()._execute_step(
            _build_post_research_state(), {}
        )
        r2 = await PruneAfterOrchestrateNode()._execute_step(
            _build_post_orchestrate_state(), {}
        )

        assert r1.status == NodeExecutionStatus.SUCCESS
        assert r2.status == NodeExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_artifact_ref_structure_intact_after_prune(self):
        """ArtifactRef dicts must retain all required fields after pruning."""
        node = PruneAfterResearchNode()
        state = _build_post_research_state()

        await node._execute_step(state, {})

        required_fields = {"key", "content_hash", "size_bytes", "created_at", "summary"}
        for ref in state["artifacts"].values():
            assert required_fields.issubset(ref.keys()), f"Missing fields in {ref}"
