"""
Deep Agent workflow graph for LangGraph v3.

This module defines a simple workflow that uses the DeepAgentNode for
sophisticated multi-step reasoning about code.
"""

from typing import Any, Dict, List, Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.context import AppContext
from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.ask_code_nodes import (
    DetermineRepoNode,
    PresentToUserNode,
    ValidateInputNode,
)
from graph_kb_api.flows.v3.nodes.deep_agent import DeepAgentNode
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.ask_code import AskCodeState
from graph_kb_api.flows.v3.tools import get_all_tools
from graph_kb_api.utils.enhanced_logger import EnhancedLogger
from graph_kb_api.utils.timeout_config import TimeoutConfig

logger = EnhancedLogger(__name__)


class DeepAgentWorkflowEngine(BaseWorkflowEngine):
    """
    Workflow engine for deep agent analysis.

    This engine provides a simplified workflow that:
    1. Validates input
    2. Determines the repository
    3. Runs the deep agent for sophisticated analysis (with semantic search tools)
    4. Presents results to user

    The deep agent handles all complex reasoning and tool calling internally,
    including semantic search via the search_code tool when needed.
    """

    def __init__(
        self,
        llm,
        app_context: AppContext,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        """
        Initialize the Deep Agent workflow engine.

        Args:
            llm: LLM instance (not used directly, deep agent has its own)
            app_context: Application context with services
            checkpointer: Optional checkpoint saver for state persistence.
                         If None, no checkpointing is used (stateless execution).
        """
        # Use settings default for max_iterations
        max_iterations = app_context.settings.deep_agent_max_iterations

        workflow_context = WorkflowContext(
            llm=llm,
            app_context=app_context,
            checkpointer=checkpointer,
        )

        super().__init__(
            workflow_context=workflow_context,
            max_iterations=max_iterations,
            workflow_name="DeepAgent",
            use_default_checkpointer=True  # Create default if checkpointer is None
        )

    def _initialize_tools(self) -> List:
        """Initialize tools for the deep agent."""
        # Get user's retrieval settings
        retrieval_config = self.app_context.get_retrieval_settings()

        # Get all tools with user's config
        return get_all_tools(retrieval_config)

    def _initialize_nodes(self) -> None:
        """Initialize all node instances."""
        self.validate_node = ValidateInputNode()
        self.determine_repo_node = DetermineRepoNode()
        self.deep_agent_node = DeepAgentNode(
            timeout_seconds=TimeoutConfig.get_deep_agent_timeout(),
            max_retries=3,
            tools=self.tools,  # Pass tools from workflow engine
            app_context=self.app_context  # Pass app_context for settings access
        )
        self.present_node = PresentToUserNode()

    def _compile_workflow(self) -> CompiledStateGraph:
        """
        Compile the workflow graph.

        Returns:
            Compiled StateGraph ready for execution
        """
        logger.info("Compiling Deep Agent workflow graph")

        # Build graph
        workflow = StateGraph(AskCodeState)

        # Add nodes
        workflow.add_node("validate", self.validate_node)
        workflow.add_node("determine_repo", self.determine_repo_node)
        workflow.add_node("deep_agent", self.deep_agent_node)
        workflow.add_node("present", self.present_node)

        # Add edges
        workflow.add_edge(START, "validate")

        workflow.add_conditional_edges(
            "validate",
            self._route_after_validate,
            {
                "determine_repo": "determine_repo",
                "present": "present"
            }
        )

        workflow.add_conditional_edges(
            "determine_repo",
            self._route_after_determine_repo,
            {
                "deep_agent": "deep_agent",
                "present": "present"
            }
        )

        workflow.add_edge("deep_agent", "present")
        workflow.add_edge("present", END)

        # Compile with checkpointer
        compiled = workflow.compile(checkpointer=self.checkpointer)

        logger.info(
            "Deep Agent workflow graph compiled successfully",
            data={'node_count': 4}
        )

        return compiled

    def _create_initial_state(
        self,
        user_query: str,
        user_id: str,
        session_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create initial workflow state.

        Args:
            user_query: User's code question
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional state fields

        Returns:
            Initial state dictionary
        """
        return {
            'original_question': user_query,  # AskCodeState expects original_question, not user_query
            'refined_question': user_query,   # Initially same as original
            'user_id': user_id,
            'session_id': session_id,
            'max_agent_iterations': self.max_iterations,
            'agent_iterations': 0,
            'messages': [],
            'question_clarity': 'clear',  # Skip clarification for deep agent
            **kwargs
        }

    def _route_after_validate(self, state: AskCodeState) -> Literal["determine_repo", "present"]:
        """Route after validation - check for errors."""
        if state.get('error'):
            logger.warning(
                "Validation failed, routing to present node",
                data={'error': state.get('error'), 'error_type': state.get('error_type')}
            )
            return "present"
        logger.info("Validation successful, proceeding to determine_repo")
        return "determine_repo"

    def _route_after_determine_repo(self, state: AskCodeState) -> Literal["deep_agent", "present"]:
        """Route after determining repo - check for errors."""
        if state.get('error'):
            logger.warning(
                "Failed to determine repository, routing to present node",
                data={'error': state.get('error'), 'error_type': state.get('error_type')}
            )
            return "present"
        logger.info("Repository determined, proceeding to deep_agent")
        return "deep_agent"
