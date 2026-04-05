"""Tests for PruneAfterResearchNode and PruneAfterOrchestrateNode."""

import pytest

from graph_kb_api.flows.v3.models.node_models import NodeExecutionStatus
from graph_kb_api.flows.v3.nodes.plan_nodes import (
    PruneAfterOrchestrateNode,
    PruneAfterResearchNode,
)


class TestPruneAfterResearchNode:
    """Test PruneAfterResearchNode clears inline data and preserves summaries."""

    @pytest.fixture
    def node(self):
        return PruneAfterResearchNode()

    @pytest.mark.asyncio
    async def test_clears_web_results(self, node):
        state = {
            "research": {
                "web_results": [{"url": "http://example.com"}],
                "approved": True,
            }
        }
        result = await node._execute_step(state, {})
        assert result.status == NodeExecutionStatus.SUCCESS
        assert "web_results" not in result.output["research"]

    @pytest.mark.asyncio
    async def test_clears_vector_results(self, node):
        state = {
            "research": {
                "vector_results": [{"chunk": "data"}],
                "findings": {"key": "val"},
            }
        }
        result = await node._execute_step(state, {})
        assert "vector_results" not in result.output["research"]

    @pytest.mark.asyncio
    async def test_clears_graph_results(self, node):
        state = {"research": {"graph_results": [{"node": "n1"}], "gaps": []}}
        result = await node._execute_step(state, {})
        assert "graph_results" not in result.output["research"]

    @pytest.mark.asyncio
    async def test_preserves_approved_flag(self, node):
        state = {"research": {"approved": True, "web_results": []}}
        result = await node._execute_step(state, {})
        assert result.output["research"]["approved"] is True

    @pytest.mark.asyncio
    async def test_preserves_findings(self, node):
        findings = {"summary": "Found 3 relevant papers"}
        state = {"research": {"findings": findings, "vector_results": [1, 2, 3]}}
        result = await node._execute_step(state, {})
        assert result.output["research"]["findings"] == findings

    @pytest.mark.asyncio
    async def test_preserves_gaps(self, node):
        state = {"research": {"gaps": [{"topic": "auth"}], "graph_results": []}}
        result = await node._execute_step(state, {})
        assert result.output["research"]["gaps"] == [{"topic": "auth"}]

    @pytest.mark.asyncio
    async def test_empty_research_state(self, node):
        state = {}
        result = await node._execute_step(state, {})
        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["research"] == {}

    @pytest.mark.asyncio
    async def test_does_not_touch_artifacts(self, node):
        """Artifacts are at top-level state, not inside research — prune node only returns research key."""
        state = {
            "research": {"web_results": [1], "approved": True},
            "artifacts": {
                "research.web_results": {
                    "key": "specs/s1/research/web",
                    "content_hash": "abc",
                }
            },
        }
        result = await node._execute_step(state, {})
        # Output only contains research key — artifacts are untouched
        assert "artifacts" not in result.output

    @pytest.mark.asyncio
    async def test_clears_all_three_keys_at_once(self, node):
        state = {
            "research": {
                "web_results": [1, 2],
                "vector_results": [3, 4],
                "graph_results": [5, 6],
                "approved": True,
                "findings": {"summary": "ok"},
                "review_feedback": "looks good",
            }
        }
        result = await node._execute_step(state, {})
        pruned = result.output["research"]
        assert "web_results" not in pruned
        assert "vector_results" not in pruned
        assert "graph_results" not in pruned
        assert pruned["approved"] is True
        assert pruned["findings"] == {"summary": "ok"}
        assert pruned["review_feedback"] == "looks good"

    def test_node_attributes(self, node):
        assert node.phase == "research"
        assert node.step_name == "prune_after_research"
        assert node.step_progress == 1.0


class TestPruneAfterOrchestrateNode:
    """Test PruneAfterOrchestrateNode clears iteration data and preserves outputs."""

    @pytest.fixture
    def node(self):
        return PruneAfterOrchestrateNode()

    @pytest.mark.asyncio
    async def test_clears_critique_history(self, node):
        state = {
            "orchestrate": {
                "critique_history": [{"round": 1}],
                "task_results": [{"id": "t1"}],
            }
        }
        result = await node._execute_step(state, {})
        assert result.status == NodeExecutionStatus.SUCCESS
        assert "critique_history" not in result.output["orchestrate"]

    @pytest.mark.asyncio
    async def test_clears_iteration_count(self, node):
        state = {"orchestrate": {"iteration_count": 5, "all_complete": True}}
        result = await node._execute_step(state, {})
        assert "iteration_count" not in result.output["orchestrate"]

    @pytest.mark.asyncio
    async def test_clears_current_task_context(self, node):
        state = {
            "orchestrate": {
                "current_task_context": {"task_id": "t1"},
                "task_results": [],
            }
        }
        result = await node._execute_step(state, {})
        assert "current_task_context" not in result.output["orchestrate"]

    @pytest.mark.asyncio
    async def test_preserves_task_results(self, node):
        results = [{"id": "t1", "status": "done"}]
        state = {"orchestrate": {"task_results": results, "critique_history": []}}
        result = await node._execute_step(state, {})
        assert result.output["orchestrate"]["task_results"] == results

    @pytest.mark.asyncio
    async def test_preserves_all_complete(self, node):
        state = {"orchestrate": {"all_complete": True, "iteration_count": 3}}
        result = await node._execute_step(state, {})
        assert result.output["orchestrate"]["all_complete"] is True

    @pytest.mark.asyncio
    async def test_preserves_task_iterations(self, node):
        iterations = {"t1": [{"iteration": 1, "approved": True}]}
        state = {
            "orchestrate": {"task_iterations": iterations, "current_task_context": {}}
        }
        result = await node._execute_step(state, {})
        assert result.output["orchestrate"]["task_iterations"] == iterations

    @pytest.mark.asyncio
    async def test_empty_orchestrate_state(self, node):
        state = {}
        result = await node._execute_step(state, {})
        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["orchestrate"] == {}

    @pytest.mark.asyncio
    async def test_does_not_touch_artifacts(self, node):
        state = {
            "orchestrate": {"critique_history": [], "task_results": [{"id": "t1"}]},
            "artifacts": {
                "orchestrate.task_t1.draft": {
                    "key": "specs/s1/orchestrate/tasks/t1/draft"
                }
            },
        }
        result = await node._execute_step(state, {})
        assert "artifacts" not in result.output

    @pytest.mark.asyncio
    async def test_clears_all_three_keys_at_once(self, node):
        state = {
            "orchestrate": {
                "critique_history": [{"round": 1}, {"round": 2}],
                "iteration_count": 5,
                "current_task_context": {"task_id": "t3"},
                "task_results": [{"id": "t1"}],
                "all_complete": False,
                "critique_feedback": "needs work",
            }
        }
        result = await node._execute_step(state, {})
        pruned = result.output["orchestrate"]
        assert "critique_history" not in pruned
        assert "iteration_count" not in pruned
        assert "current_task_context" not in pruned
        assert pruned["task_results"] == [{"id": "t1"}]
        assert pruned["all_complete"] is False
        assert pruned["critique_feedback"] == "needs work"

    def test_node_attributes(self, node):
        assert node.phase == "orchestrate"
        assert node.step_name == "prune_after_orchestrate"
        assert node.step_progress == 1.0
