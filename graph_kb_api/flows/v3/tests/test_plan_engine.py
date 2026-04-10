"""Tests for PlanEngine parent graph."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graph_kb_api.flows.v3.graphs.plan_engine import PlanEngine
from graph_kb_api.flows.v3.models.node_models import NodeExecutionStatus
from graph_kb_api.flows.v3.nodes.plan_nodes import FinalizeNode
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext


@pytest.fixture
def workflow_context():
    """Create a minimal WorkflowContext for testing."""
    mock_llm = MagicMock()
    mock_llm.name = "test-llm"
    return WorkflowContext(
        llm=mock_llm,
        app_context=None,
        artifact_service=None,
        blob_storage=None,
        checkpointer=None,
    )


class TestPlanEngineInit:
    """Test PlanEngine initialization and compilation."""

    def test_engine_compiles(self, workflow_context):
        """PlanEngine compiles without errors."""
        engine = PlanEngine(workflow_context)
        assert engine.workflow is not None

    def test_engine_has_subgraphs(self, workflow_context):
        """PlanEngine initializes all 5 subgraphs."""
        engine = PlanEngine(workflow_context)
        assert engine.context_subgraph is not None
        assert engine.research_subgraph is not None
        assert engine.planning_subgraph is not None
        assert engine.orchestrate_subgraph is not None
        assert engine.assembly_subgraph is not None

    def test_engine_has_prune_nodes(self, workflow_context):
        """PlanEngine initializes both prune nodes."""
        engine = PlanEngine(workflow_context)
        assert engine.prune_after_research is not None
        assert engine.prune_after_orchestrate is not None

    def test_workflow_name(self, workflow_context):
        """PlanEngine has correct workflow name."""
        engine = PlanEngine(workflow_context)
        assert engine.workflow_name == "plan_engine"

    def test_tools_empty(self, workflow_context):
        """PlanEngine has no standalone tools."""
        engine = PlanEngine(workflow_context)
        assert engine.tools == []


class TestBuildInitialState:
    """Test _build_initial_state budget initialization."""

    def test_default_budget(self, workflow_context):
        """Default budget values are set correctly."""
        engine = PlanEngine(workflow_context)
        state = engine._build_initial_state({})
        budget = state["budget"]
        assert budget["max_llm_calls"] == 200
        assert budget["remaining_llm_calls"] == 200
        assert budget["max_tokens"] == 500_000
        assert budget["tokens_used"] == 0
        assert budget["max_wall_clock_s"] == 1800

    def test_budget_started_at_is_iso(self, workflow_context):
        """started_at is a valid ISO 8601 timestamp."""
        engine = PlanEngine(workflow_context)
        state = engine._build_initial_state({})
        started_at = state["budget"]["started_at"]
        # Should parse without error
        datetime.fromisoformat(started_at)

    def test_custom_budget_from_seed(self, workflow_context):
        """Seed values override budget defaults."""
        engine = PlanEngine(workflow_context)
        seed = {
            "max_llm_calls": 50,
            "max_tokens": 100_000,
            "max_wall_clock_s": 600,
        }
        state = engine._build_initial_state(seed)
        budget = state["budget"]
        assert budget["max_llm_calls"] == 50
        assert budget["remaining_llm_calls"] == 50
        assert budget["max_tokens"] == 100_000
        assert budget["max_wall_clock_s"] == 600
        assert budget["tokens_used"] == 0

    def test_initial_state_fields(self, workflow_context):
        """Initial state has all required tracking fields."""
        engine = PlanEngine(workflow_context)
        state = engine._build_initial_state({})
        assert state["artifacts"] == {}
        assert state["transition_log"] == []
        assert state["fingerprints"] == {}
        assert state["completed_phases"] == {}
        assert state["workflow_status"] == "running"

    def test_seed_values_preserved(self, workflow_context):
        """Seed values are spread into the initial state."""
        engine = PlanEngine(workflow_context)
        seed = {"session_id": "test-123", "extra": "data"}
        state = engine._build_initial_state(seed)
        assert state["session_id"] == "test-123"
        assert state["extra"] == "data"


class TestConfigWithServices:
    """Test service auto-injection into config."""

    def test_injects_artifact_service(self, workflow_context):
        """Non-None services are wired into configurable."""
        # workflow_context has artifact_service=None, so it should NOT be injected
        engine = PlanEngine(workflow_context)
        config = engine.get_config_with_services()
        assert "artifact_service" not in config["configurable"]
        # llm is non-None, so it should be injected
        assert config["configurable"]["llm"] is workflow_context.llm

    def test_preserves_existing_config(self, workflow_context):
        """Existing config values are preserved."""
        engine = PlanEngine(workflow_context)
        config = engine.get_config_with_services({"configurable": {"thread_id": "abc"}})
        assert config["configurable"]["thread_id"] == "abc"
        # llm is non-None, so it should be injected
        assert config["configurable"]["llm"] is workflow_context.llm

    def test_handles_none_config(self, workflow_context):
        """None config creates a new dict."""
        engine = PlanEngine(workflow_context)
        config = engine.get_config_with_services(None)
        assert "configurable" in config
        # context alias is always set
        assert config["configurable"]["context"] is workflow_context

    def test_context_alias_always_present(self, workflow_context):
        """Backward-compatible 'context' alias is always set."""
        engine = PlanEngine(workflow_context)
        config = engine.get_config_with_services()
        assert config["configurable"]["context"] is workflow_context

    def test_auto_injects_all_non_none_fields(self):
        """All non-None WorkflowContext fields are injected."""
        mock_llm = MagicMock()
        mock_llm.name = "test-llm"
        mock_artifact = MagicMock()
        mock_blob = MagicMock()
        wc = WorkflowContext(
            llm=mock_llm,
            app_context=None,
            artifact_service=mock_artifact,
            blob_storage=mock_blob,
            checkpointer=None,
        )
        engine = PlanEngine(wc)
        config = engine.get_config_with_services()
        configurable = config["configurable"]
        assert configurable["llm"] is mock_llm
        assert configurable["artifact_service"] is mock_artifact
        assert configurable["blob_storage"] is mock_blob
        # None fields should not be present
        assert "app_context" not in configurable
        assert "checkpointer" not in configurable
        assert "vector_store" not in configurable


class TestFinalizeNodeWiring:
    """Test FinalizeNode is present and wired after assembly."""

    def test_engine_has_finalize_node(self, workflow_context):
        """PlanEngine initializes the finalize node."""
        engine = PlanEngine(workflow_context)
        assert engine.finalize is not None

    def test_finalize_node_in_graph(self, workflow_context):
        """Finalize node is registered in the compiled graph."""
        engine = PlanEngine(workflow_context)
        node_names = list(engine.workflow.get_graph().nodes.keys())
        assert "finalize" in node_names

    def test_finalize_wired_after_assembly(self, workflow_context):
        """Finalize node receives an edge from assembly."""
        engine = PlanEngine(workflow_context)
        graph = engine.workflow.get_graph()
        # Check that assembly has an edge to finalize
        assembly_targets = [edge.target for edge in graph.edges if edge.source == "assembly"]
        assert "finalize" in assembly_targets

    def test_finalize_wired_to_end(self, workflow_context):
        """Finalize node has an edge to __end__."""
        engine = PlanEngine(workflow_context)
        graph = engine.workflow.get_graph()
        finalize_targets = [edge.target for edge in graph.edges if edge.source == "finalize"]
        assert "__end__" in finalize_targets

    def test_assembly_wires_to_finalize_and_end(self, workflow_context):
        """Assembly routes to finalize on approval and __end__ on rejection."""
        engine = PlanEngine(workflow_context)
        graph = engine.workflow.get_graph()
        assembly_targets = [edge.target for edge in graph.edges if edge.source == "assembly"]
        assert "finalize" in assembly_targets
        assert "__end__" in assembly_targets


class TestFinalizeNodeExecuteStep:
    """Test FinalizeNode._execute_step returns success and emits complete."""

    @pytest.mark.asyncio
    async def test_execute_step_returns_success(self):
        """FinalizeNode._execute_step returns a success result."""
        node = FinalizeNode()
        state = {
            "session_id": "sess-1",
            "generate": {
                "spec_document_path": "/docs/spec.md",
                "story_cards_path": "/docs/stories",
            },
        }
        config = {"configurable": {"client_id": "client-1"}}

        with patch(
            "graph_kb_api.flows.v3.nodes.plan.assembly_nodes.emit_complete",
            new_callable=AsyncMock,
        ):
            result = await node._execute_step(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "completed"
        assert result.output["completed_phases"]["assembly"] is True

    @pytest.mark.asyncio
    async def test_execute_step_calls_emit_complete(self):
        """FinalizeNode._execute_step calls emit_complete with correct args."""
        node = FinalizeNode()
        state = {
            "session_id": "sess-42",
            "generate": {
                "spec_document_path": "/output/spec.md",
                "story_cards_path": "/output/stories.md",
            },
        }
        config = {"configurable": {"client_id": "ws-client"}}

        with patch(
            "graph_kb_api.flows.v3.nodes.plan.assembly_nodes.emit_complete",
            new_callable=AsyncMock,
        ) as mock_emit:
            await node._execute_step(state, config)

        mock_emit.assert_awaited_once_with(
            session_id="sess-42",
            document_manifest=None,
            spec_document_url="/output/spec.md",
            client_id="ws-client",
        )

    @pytest.mark.asyncio
    async def test_execute_step_completes_when_manifest_exists_without_spec_path(self):
        """Manifest-backed output should still finalize as completed."""
        node = FinalizeNode()
        manifest = {
            "spec_name": "FedEx Carrier Integration",
            "entries": [
                {
                    "task_id": "task-1",
                    "spec_section": "Overview",
                    "status": "final",
                    "artifact_ref": {"key": "specs/sess-manifest/deliverables/task-1.md"},
                }
            ],
            "total_documents": 1,
            "total_tokens": 128,
            "composed_index_ref": {"key": "output/index.md"},
        }
        state = {
            "session_id": "sess-manifest",
            "generate": {},
            "document_manifest": manifest,
        }
        config = {"configurable": {"client_id": "client-7"}}

        with patch(
            "graph_kb_api.flows.v3.nodes.plan.assembly_nodes.emit_complete",
            new_callable=AsyncMock,
        ) as mock_emit:
            result = await node._execute_step(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "completed"
        assert result.output["completed_phases"]["assembly"] is True
        mock_emit.assert_awaited_once_with(
            session_id="sess-manifest",
            document_manifest=manifest,
            spec_document_url="output/index.md",
            client_id="client-7",
        )

    @pytest.mark.asyncio
    async def test_execute_step_handles_missing_generate(self):
        """FinalizeNode handles missing generate state gracefully."""
        node = FinalizeNode()
        state = {"session_id": "sess-empty"}
        config = {"configurable": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.plan.assembly_nodes.emit_complete",
            new_callable=AsyncMock,
        ) as mock_emit:
            result = await node._execute_step(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        mock_emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finalize_node_attributes(self):
        """FinalizeNode has correct phase, step_name, and step_progress."""
        node = FinalizeNode()
        assert node.phase == "assembly"
        assert node.step_name == "finalize"
        assert node.step_progress == 1.0


class TestRouteAfterAssembly:
    """Test PlanEngine routing after assembly completion."""

    def test_budget_accepted_assembly_results_route_to_finalize(self):
        """Accepted assembly budget results should still finalize."""
        state = {
            "workflow_status": "running",
            "completed_phases": {
                "context": True,
                "research": True,
                "planning": True,
                "orchestrate": True,
                "assembly": True,
            },
            "completeness": {
                "approval_decision": "approve",
                "accepted_budget_exhausted_results": True,
            },
        }

        assert PlanEngine._route_after_assembly(state) == "finalize"
