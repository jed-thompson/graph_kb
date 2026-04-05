"""
AskCode agentic workflow graph for LangGraph v3.

This module defines the complete AskCode workflow with iterative tool calling,
clarification loops, and agentic behavior. The workflow supports up to 5 iterations
of tool calling before forcing completion.
"""

from typing import Any, Dict, List, Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.context import AppContext
from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.ask_code_nodes import (
    AnalyzeQuestionNode,
    ClarificationNode,
    FormatResponseNode,
    GraphExpansionNode,
    PresentToUserNode,
    SemanticRetrievalNode,
    ValidateInputNode,
)
from graph_kb_api.flows.v3.nodes.llm import LLMAgentNode
from graph_kb_api.flows.v3.nodes.tools import AgenticToolNode
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.ask_code import AskCodeState
from graph_kb_api.flows.v3.tools import get_all_tools
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class AskCodeWorkflowEngine(BaseWorkflowEngine):
    """
    Workflow engine for AskCode agentic workflows.

    This engine manages the complete lifecycle of code analysis workflows including:
    - Tool initialization and binding
    - Node instantiation
    - Graph compilation with checkpointing
    - Service injection
    - Workflow execution

    The engine compiles the workflow once during initialization and reuses it
    for all subsequent executions, improving performance and resource management.
    """

    def __init__(
        self,
        llm,
        app_context: AppContext,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        max_iterations: int = 5,
        use_default_checkpointer: bool = True,
    ):
        """
        Initialize the AskCode workflow engine.

        Args:
            llm: LLM instance to use for agent
            app_context: Application context with services
            checkpointer: Optional checkpointer for state persistence
            max_iterations: Maximum number of tool calling iterations (default: 5)
            use_default_checkpointer: If True and checkpointer is None, create default checkpointer.
                                     If False, respect None as "no checkpointing".
        """
        workflow_context = WorkflowContext(
            llm=llm,
            app_context=app_context,
            graph_store=app_context.graph_kb_facade,
            checkpointer=checkpointer,
        )

        graph_store = workflow_context.graph_store
        if graph_store is None or graph_store.prompt_manager is None:
            raise RuntimeError(
                "GraphKBFacade and its prompt_manager must be initialized before creating AskCodeWorkflowEngine"
            )
        self.agent_system_prompt = graph_store.prompt_manager.get_system_prompt()

        super().__init__(
            workflow_context=workflow_context,
            max_iterations=max_iterations,
            workflow_name="AskCode",
            use_default_checkpointer=use_default_checkpointer,
        )

    def _initialize_tools(self) -> List:
        """Initialize all tools for the workflow with user's retrieval config.

        Merges native GraphKB tools with MCP tools if MCP service is available.
        """
        # Get user's retrieval settings from app_context
        retrieval_config = self.app_context.get_retrieval_settings()

        # Get all native tools with user's config
        tools = get_all_tools(retrieval_config)

        # Merge MCP tools if available
        mcp_service = self.app_context.mcp_service
        if mcp_service is not None:
            try:
                # Load configured MCP servers (async, but we're in sync context)
                # For now, just check if any servers are configured
                servers = mcp_service.load_configured_servers()
                if servers:
                    logger.info(
                        f"MCP integration enabled with {len(servers)} server(s)",
                        data={"servers": [s.id for s in servers]},
                    )
                    # Note: Full MCP tool connection requires async initialization
                    # MCP tools will be available after calling mcp_service.connect_all()
                    # This is typically done during application startup
            except Exception as e:
                logger.warning(f"Failed to load MCP tools: {e}")

        return tools

    def _initialize_nodes(self) -> None:
        """Initialize all node instances."""
        self.validate_node = ValidateInputNode()
        self.analyze_node = AnalyzeQuestionNode()
        self.clarify_node = ClarificationNode()
        self.retrieve_node = SemanticRetrievalNode()
        self.graph_expansion_node = GraphExpansionNode()
        assert self.workflow_context.llm is not None
        self.agent_node = LLMAgentNode(self.workflow_context.llm.bind_tools(self.tools), self.agent_system_prompt)
        self.tool_node = AgenticToolNode(self.tools)
        self.format_node = FormatResponseNode()
        self.present_node = PresentToUserNode()

    def _compile_workflow(self) -> CompiledStateGraph:
        """
        Compile the workflow graph.

        This method builds the complete workflow graph with all nodes, edges,
        and routing logic, then compiles it with the checkpointer.

        Returns:
            Compiled StateGraph ready for execution
        """
        logger.info("Compiling AskCode workflow graph")

        # Build graph
        workflow = StateGraph(AskCodeState)

        # Add nodes (use node instances, not .execute method)
        # LangGraph will call the node's __call__ method which handles service injection
        workflow.add_node("validate", self.validate_node)
        workflow.add_node("analyze_question", self.analyze_node)
        workflow.add_node("clarify", self.clarify_node)
        workflow.add_node("retrieve", self.retrieve_node)
        workflow.add_node("graph_expansion", self.graph_expansion_node)
        workflow.add_node("agent", self.agent_node)
        workflow.add_node("tools", self.tool_node)
        workflow.add_node("format", self.format_node)
        workflow.add_node("present", self.present_node)

        # Add edges
        workflow.add_edge(START, "validate")

        workflow.add_conditional_edges(
            "validate",
            self._route_after_validate,
            {"analyze_question": "analyze_question", "__end__": END},
        )

        workflow.add_conditional_edges(
            "analyze_question",
            self._route_after_analyze,
            {"clarify": "clarify", "retrieve": "retrieve"},
        )

        workflow.add_edge("clarify", "retrieve")

        # Add edge from retrieve to graph_expansion
        workflow.add_conditional_edges(
            "retrieve",
            self._route_after_retrieve,
            {"graph_expansion": "graph_expansion", "__end__": END},
        )

        # Add edge from graph_expansion to agent
        workflow.add_edge("graph_expansion", "agent")

        # Agentic loop: agent -> tools -> agent (with iteration limit)
        workflow.add_conditional_edges(
            "agent",
            self._route_after_agent,
            {"tools": "tools", "format": "format", "__end__": END},
        )

        workflow.add_edge("tools", "agent")  # Loop back to agent after tool execution
        workflow.add_edge("format", "present")
        workflow.add_edge("present", END)

        # Compile with checkpointer
        compiled = workflow.compile(checkpointer=self.checkpointer)

        logger.info("AskCode workflow graph compiled successfully", data={"node_count": 9})

        return compiled

    def _create_initial_state(self, user_query: str, user_id: str, session_id: str, **kwargs) -> Dict[str, Any]:
        """
        Create initial workflow state for AskCode.

        Args:
            user_query: User's code question
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional state fields

        Returns:
            Initial state dictionary
        """
        return {
            "user_query": user_query,
            "user_id": user_id,
            "session_id": session_id,
            "max_agent_iterations": self.max_iterations,
            "agent_iterations": 0,
            "messages": [],
            "retrieved_context": [],
            "question_clarity": "unknown",
            "vector_search_duration": 0.0,
            **kwargs,
        }

    def _route_after_validate(self, state: AskCodeState) -> Literal["analyze_question", "__end__"]:
        """Route after validation - check for errors."""
        if state.get("error"):
            logger.warning(
                "Validation failed, ending workflow",
                data={
                    "error": state.get("error"),
                    "error_type": state.get("error_type"),
                },
            )
            return "__end__"
        logger.info("Validation successful, proceeding to analyze_question")
        return "analyze_question"

    def _route_after_analyze(self, state: AskCodeState) -> Literal["clarify", "retrieve"]:
        """Route after question analysis - clarify if vague."""
        clarity = state.get("question_clarity", "clear")
        if clarity == "vague" or clarity == "ambiguous":
            logger.info(f"Question is {clarity}, requesting clarification")
            return "clarify"
        logger.info("Question is clear, proceeding to retrieval")
        return "retrieve"

    def _route_after_retrieve(self, state: AskCodeState) -> Literal["graph_expansion", "__end__"]:
        """Route after retrieval - check for errors."""
        if state.get("error"):
            error_msg = state.get("error", "Unknown error")
            error_type = state.get("error_type", "unknown")
            logger.error(
                f"Retrieval failed, ending workflow: {error_msg}",
                data={"error": error_msg, "error_type": error_type},
            )
            return "__end__"

        context_items = state.get("context_items", [])
        logger.info(
            "Retrieval successful, proceeding to graph_expansion",
            data={"context_items_count": len(context_items)},
        )
        return "graph_expansion"

    def _route_after_agent(self, state: AskCodeState) -> Literal["tools", "format", "__end__"]:
        """
        Route after agent - check if tools should be called or if we're done.

        Enforces max iterations limit.
        """
        messages = state.get("messages", [])
        if not messages:
            logger.warning("No messages from agent, ending workflow")
            return "__end__"

        last_message = messages[-1]

        # Check if agent wants to call tools
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            # Check iteration limit
            iterations = state.get("agent_iterations", 0)
            max_iterations = state.get("max_agent_iterations", self.max_iterations)

            if iterations >= max_iterations:
                logger.warning(
                    f"Max iterations ({max_iterations}) reached, forcing completion",
                    data={"iterations": iterations},
                )
                return "format"

            logger.info(
                f"Agent requesting tools (iteration {iterations + 1}/{max_iterations})",
                data={"tool_count": len(last_message.tool_calls)},
            )
            return "tools"

        # Agent provided final answer
        logger.info("Agent provided final answer, formatting response")
        return "format"
