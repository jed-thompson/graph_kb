"""
Differential Update workflow graph for LangGraph v3.

This module defines the complete differential update workflow with impact analysis,
user file selection, rollback capability, and verification. The workflow supports
pause/resume functionality and human-in-the-loop interactions.
"""

from typing import Any, Dict, Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.context import AppContext
from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.diff_nodes import (
    ApplyUpdatesNode,
    AwaitUserSelectionNode,
    ComputeDiffNode,
    CreateRollbackCheckpointNode,
    ExecuteRollbackNode,
    FetchUpdatesNode,
    GenerateImpactAnalysisNode,
    OfferRollbackNode,
    ParseDiffArgumentsNode,
    PresentChangesNode,
    QueryExistingSymbolsNode,
    ValidateRepositoryIndexedNode,
    VerifyUpdatesNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.diff import DiffState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class DiffWorkflowEngine(BaseWorkflowEngine):
    """
    Workflow engine for differential update workflows.

    This engine manages the complete lifecycle of differential repository updates including:
    - Repository validation and update fetching
    - Diff computation (changed/deleted files)
    - Impact analysis with LLM
    - User file selection (human-in-the-loop)
    - Rollback checkpoint creation
    - Update application
    - Verification with rollback option

    The engine compiles the workflow once during initialization and reuses it
    for all subsequent executions, improving performance and resource management.
    """

    def __init__(self, llm, app_context: AppContext, checkpointer: Optional[BaseCheckpointSaver] = None):
        """
        Initialize the Diff workflow engine.

        Args:
            llm: LLM instance for impact analysis
            app_context: Application context with services (GraphKBFacade, etc.)
            checkpointer: Optional checkpointer for state persistence
        """
        workflow_context = WorkflowContext(
            llm=llm,
            app_context=app_context,
            checkpointer=checkpointer,
        )

        super().__init__(
            workflow_context=workflow_context,
            max_iterations=0,  # Not applicable for diff
            workflow_name="Diff",
        )

    def _initialize_tools(self):
        """Initialize tools (not used in diff workflow)."""
        return []

    def _initialize_nodes(self) -> None:
        """Initialize all node instances."""
        self.parse_args_node = ParseDiffArgumentsNode()
        self.validate_repo_node = ValidateRepositoryIndexedNode()
        self.fetch_updates_node = FetchUpdatesNode()
        self.compute_diff_node = ComputeDiffNode()
        self.query_symbols_node = QueryExistingSymbolsNode()
        self.impact_analysis_node = GenerateImpactAnalysisNode()
        self.present_changes_node = PresentChangesNode()
        self.await_selection_node = AwaitUserSelectionNode()
        self.create_checkpoint_node = CreateRollbackCheckpointNode()
        self.apply_updates_node = ApplyUpdatesNode()
        self.verify_updates_node = VerifyUpdatesNode()
        self.offer_rollback_node = OfferRollbackNode()
        self.execute_rollback_node = ExecuteRollbackNode()

    def _compile_workflow(self) -> CompiledStateGraph:
        """
        Compile the workflow graph.

        This method builds the complete workflow graph with all nodes, edges,
        and routing logic for differential updates, then compiles it with the
        checkpointer for pause/resume functionality.

        Returns:
            Compiled StateGraph ready for execution
        """
        logger.info("Compiling Diff workflow graph")

        # Build graph
        workflow = StateGraph(DiffState)

        # Add nodes
        workflow.add_node("parse_args", self.parse_args_node)
        workflow.add_node("validate_repo", self.validate_repo_node)
        workflow.add_node("fetch_updates", self.fetch_updates_node)
        workflow.add_node("compute_diff", self.compute_diff_node)
        workflow.add_node("query_symbols", self.query_symbols_node)
        workflow.add_node("impact_analysis", self.impact_analysis_node)
        workflow.add_node("present_changes", self.present_changes_node)
        workflow.add_node("await_selection", self.await_selection_node)
        workflow.add_node("create_checkpoint", self.create_checkpoint_node)
        workflow.add_node("apply_updates", self.apply_updates_node)
        workflow.add_node("verify_updates", self.verify_updates_node)
        workflow.add_node("offer_rollback", self.offer_rollback_node)
        workflow.add_node("execute_rollback", self.execute_rollback_node)

        # Add edges
        workflow.add_edge(START, "parse_args")

        # Validation chain (Requirement 3.1)
        workflow.add_conditional_edges(
            "parse_args", self._route_after_parse, {"validate_repo": "validate_repo", "__end__": END}
        )

        workflow.add_conditional_edges(
            "validate_repo", self._route_after_validate, {"fetch_updates": "fetch_updates", "__end__": END}
        )

        workflow.add_conditional_edges(
            "fetch_updates", self._route_after_fetch, {"compute_diff": "compute_diff", "__end__": END}
        )

        # Diff computation and impact analysis (Requirements 3.1, 3.2, 3.3)
        workflow.add_conditional_edges(
            "compute_diff", self._route_after_diff, {"query_symbols": "query_symbols", "no_changes": END}
        )

        workflow.add_edge("query_symbols", "impact_analysis")
        workflow.add_edge("impact_analysis", "present_changes")
        workflow.add_edge("present_changes", "await_selection")

        # User selection routing (Requirement 3.4)
        workflow.add_conditional_edges(
            "await_selection", self._route_after_selection, {"create_checkpoint": "create_checkpoint", "cancel": END}
        )

        # Update application (Requirement 3.5)
        workflow.add_edge("create_checkpoint", "apply_updates")

        workflow.add_conditional_edges(
            "apply_updates", self._route_after_apply, {"verify_updates": "verify_updates", "__end__": END}
        )

        # Verification and rollback (Requirements 3.6, 3.7)
        workflow.add_conditional_edges(
            "verify_updates", self._route_after_verify, {"success": END, "offer_rollback": "offer_rollback"}
        )

        workflow.add_conditional_edges(
            "offer_rollback",
            self._route_after_rollback_offer,
            {"execute_rollback": "execute_rollback", "keep_changes": END},
        )

        workflow.add_edge("execute_rollback", END)

        # Compile with checkpointer for pause/resume
        compiled = workflow.compile(checkpointer=self.checkpointer)

        logger.info("Diff workflow graph compiled successfully", data={"node_count": 13})

        return compiled

    def _create_initial_state(self, user_query: str, user_id: str, session_id: str, **kwargs) -> Dict[str, Any]:
        """
        Create initial workflow state for Diff.

        Args:
            user_query: Repository URL to update
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional state fields

        Returns:
            Initial state dictionary
        """
        return {
            "args": [user_query],
            "repo_url": user_query,
            "user_id": user_id,
            "session_id": session_id,
            "repo_indexed": False,
            "has_changes": False,
            "changed_files": [],
            "deleted_files": [],
            "existing_symbols": [],
            "verification_passed": False,
            "rollback_offered": False,
            **kwargs,
        }

    # Routing functions

    def _route_after_parse(self, state: DiffState) -> Literal["validate_repo", "__end__"]:
        """Route after argument parsing."""
        if state.get("error"):
            logger.warning(f"Parse error: {state.get('error')}")
            return "__end__"
        return "validate_repo"

    def _route_after_validate(self, state: DiffState) -> Literal["fetch_updates", "__end__"]:
        """Route after repository validation."""
        if state.get("error") or not state.get("repo_indexed", False):
            logger.warning(f"Repository validation failed: {state.get('error')}")
            return "__end__"
        return "fetch_updates"

    def _route_after_fetch(self, state: DiffState) -> Literal["compute_diff", "__end__"]:
        """Route after fetching updates."""
        if state.get("error"):
            logger.error(f"Fetch error: {state.get('error')}")
            return "__end__"
        return "compute_diff"

    def _route_after_diff(self, state: DiffState) -> Literal["query_symbols", "no_changes"]:
        """
        Route after diff computation.
        """
        has_changes = state.get("has_changes", False)

        if not has_changes:
            logger.info("No changes detected, ending workflow")
            return "no_changes"

        changed_files = state.get("changed_files", [])
        deleted_files = state.get("deleted_files", [])

        logger.info(
            f"Changes detected: {len(changed_files)} changed, {len(deleted_files)} deleted",
            data={"changed_count": len(changed_files), "deleted_count": len(deleted_files)},
        )

        return "query_symbols"

    def _route_after_selection(self, state: DiffState) -> Literal["create_checkpoint", "cancel"]:
        """
        Route after user file selection.
        """
        approved = state.get("user_approved_update", False)

        if not approved:
            logger.info("User cancelled update")
            return "cancel"

        selected_files = state.get("selected_files", [])
        logger.info(f"User approved update for {len(selected_files)} files", data={"file_count": len(selected_files)})

        return "create_checkpoint"

    def _route_after_apply(self, state: DiffState) -> Literal["verify_updates", "__end__"]:
        """
        Route after applying updates.
        """
        if state.get("error"):
            logger.error(f"Update application failed: {state.get('error')}")
            return "__end__"

        if not state.get("updates_applied", False):
            logger.warning("Updates not applied")
            return "__end__"

        logger.info("Updates applied successfully, proceeding to verification")
        return "verify_updates"

    def _route_after_verify(self, state: DiffState) -> Literal["success", "offer_rollback"]:
        """
        Route after verification.
        """
        verification_passed = state.get("verification_passed", False)

        if verification_passed:
            logger.info("Verification passed, workflow complete")
            return "success"

        logger.warning("Verification failed, offering rollback")
        return "offer_rollback"

    def _route_after_rollback_offer(self, state: DiffState) -> Literal["execute_rollback", "keep_changes"]:
        """
        Route after rollback offer.
        """
        should_rollback = state.get("user_rollback_decision", False)

        if should_rollback:
            logger.info("User chose to rollback changes")
            return "execute_rollback"

        logger.info("User chose to keep changes despite verification failure")
        return "keep_changes"


def create_diff_workflow(llm, app_context, checkpointer: Optional[BaseCheckpointSaver] = None) -> CompiledStateGraph:
    """
    Create and compile the differential update workflow.

    This is the main entry point for creating a Diff workflow instance.
    The workflow includes:
    - Repository validation and update fetching
    - Diff computation (changed/deleted files)
    - Impact analysis with LLM
    - User file selection (human-in-the-loop)
    - Rollback checkpoint creation
    - Update application
    - Verification with rollback option

    Args:
        llm: LLM instance for impact analysis
        app_context: Application context with GraphKBFacade and other services
        checkpointer: Optional checkpointer for state persistence (pause/resume)

    Returns:
        Compiled StateGraph ready for execution

    Example:
        >>> from langgraph.checkpoint.memory import MemorySaver
        >>> checkpointer = MemorySaver()
        >>> workflow = create_diff_workflow(llm, app_context, checkpointer)
        >>>
        >>> # Execute workflow
        >>> config = {"configurable": {"thread_id": "user123_session456"}}
        >>> result = await workflow.ainvoke(
        ...     {
        ...         'args': ['https://github.com/owner/repo'],
        ...         'user_id': 'user123',
        ...         'session_id': 'session456'
        ...     },
        ...     config=config
        ... )
        >>>
        >>> # Resume after interrupt (e.g., after user file selection)
        >>> from langgraph.types import Command
        >>> result = await workflow.ainvoke(
        ...     Command(resume={'decision': 'all', 'selected_files': []}),
        ...     config=config
        ... )

    """
    logger.info("Creating Diff workflow")

    engine = DiffWorkflowEngine(llm=llm, app_context=app_context, checkpointer=checkpointer)

    return engine.workflow
