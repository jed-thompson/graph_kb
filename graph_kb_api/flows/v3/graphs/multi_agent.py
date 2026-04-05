"""
Multi-agent workflow engine for GraphKB.

Orchestates task breakdown, agent coordination, review, and result aggregation
into a cohesive workflow powered by LangGraph.
"""

from langgraph.graph import END, START, StateGraph

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.multi_agent import (
    AgentCoordinatorNode,
    ClarificationNode,
    InputPrepareNode,
    MultiPassReviewNode,
    QualityCheckNode,
    RePromptAgent,
    ResultAggregationNode,
    TaskBreakdownNode,
    TaskClassifierNode,
    ToolSelectorNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.multi_agent import MultiAgentState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class MultiAgentWorkflowEngine(BaseWorkflowEngine):
    """
    Workflow engine for multi-agent task processing.

    Orchestrates:
    - Input preparation and clarification
    - Task breakdown and classification
    - Agent coordination (parallel/sequential based on dependencies)
    - Tool assignment based on agent capabilities
    - Multi-pass review (completion, quality, security)
    - Result aggregation and conflict resolution
    """

    def __init__(self, llm, app_context, checkpointer=None):
        """
        Initialize multi-agent workflow engine.

        Args:
            llm: Language model instance
            app_context: Application context with services
            checkpointer: Checkpointer for state persistence
        """
        workflow_context = WorkflowContext(
            llm=llm,
            app_context=app_context,
            checkpointer=checkpointer,
        )

        super().__init__(
            workflow_context=workflow_context,
            max_iterations=app_context.settings.multi_agent_max_iterations or 10,
            workflow_name="MultiAgent",
        )

    def _initialize_tools(self):
        """
        Get all available tools for multi-agent workflow.

        Returns:
            List of all available tools
        """
        from graph_kb_api.flows.v3.tools import get_all_tools

        retrieval_config = self.app_context.get_retrieval_settings()
        all_tools = get_all_tools(retrieval_config)

        logger.info(f"Initialized {len(all_tools)} tools for multi-agent workflow")

        return all_tools

    def _initialize_nodes(self):
        """
        Initialize all node instances for multi-agent workflow.
        """
        # Input and breakdown
        self.input_prepare_node = InputPrepareNode()
        self.task_breakdown_node = TaskBreakdownNode()
        self.task_classifier_node = TaskClassifierNode()

        # Agent execution
        self.agent_coordinator_node = AgentCoordinatorNode()
        self.tool_selector_node = ToolSelectorNode()

        # Review and quality
        self.multi_pass_review_node = MultiPassReviewNode()
        self.quality_check_node = QualityCheckNode()
        self.reprompt_agent_node = RePromptAgent()

        # Result aggregation
        self.result_aggregation_node = ResultAggregationNode()

        # Clarification
        self.clarification_node = ClarificationNode()

        logger.info("All multi-agent workflow nodes initialized")

    def _compile_workflow(self):
        """
        Compile the LangGraph state machine.

        Returns:
            Compiled state graph ready for execution
        """
        workflow = StateGraph(MultiAgentState)

        # Add all nodes to the graph
        workflow.add_node("input_prepare", self.input_prepare_node)
        workflow.add_node("task_breakdown", self.task_breakdown_node)
        workflow.add_node("task_classifier", self.task_classifier_node)
        workflow.add_node("agent_coordinator", self.agent_coordinator_node)
        workflow.add_node("tool_selector", self.tool_selector_node)
        workflow.add_node("multi_pass_review", self.multi_pass_review_node)
        workflow.add_node("quality_check", self.quality_check_node)
        workflow.add_node("reprompt_agent", self.reprompt_agent_node)
        workflow.add_node("result_aggregation", self.result_aggregation_node)
        workflow.add_node("clarification", self.clarification_node)

        # Add edges for workflow flow

        # Start -> input_prepare
        workflow.add_edge(START, "input_prepare")

        # input_prepare -> conditional (breakdown or clarification)
        workflow.add_conditional_edges(
            "input_prepare",
            self._route_after_input,
            {
                "task_breakdown": "task_breakdown",
                "clarification": "clarification",
            },
        )

        # task_breakdown -> task_classifier
        workflow.add_edge("task_breakdown", "task_classifier")

        # task_classifier -> agent_coordinator
        workflow.add_edge("task_classifier", "agent_coordinator")

        # agent_coordinator -> tool_selector
        workflow.add_edge("agent_coordinator", "tool_selector")

        # tool_selector -> agent_execution (agent_coordinator with tools)
        workflow.add_edge("tool_selector", "agent_coordinator")

        # agent_coordinator -> multi_pass_review
        workflow.add_edge("agent_coordinator", "multi_pass_review")

        # multi_pass_review -> conditional (quality_check or reprompt or result_aggregation)
        workflow.add_conditional_edges(
            "multi_pass_review",
            self._route_after_review,
            {
                "quality_check": "quality_check",
                "reprompt_agent": "reprompt_agent",
                "result_aggregation": "result_aggregation",
            },
        )

        # quality_check -> multi_pass_review
        workflow.add_edge("quality_check", "multi_pass_review")

        # reprompt_agent -> agent_coordinator
        workflow.add_edge("reprompt_agent", "agent_coordinator")

        # result_aggregation -> END
        workflow.add_edge("result_aggregation", END)

        logger.info("Multi-agent workflow graph compiled")

        return workflow.compile(checkpointer=self.checkpointer)

    def _route_after_input(self, state: MultiAgentState) -> str:
        """
        Route after input preparation.

        Args:
            state: Current workflow state

        Returns:
            Next node name to route to
        """
        if state.get("awaiting_clarification", False):
            return "clarification"
        return "task_breakdown"

    def _route_after_review(self, state: MultiAgentState) -> str:
        """
        Route after multi-pass review.

        Args:
            state: Current workflow state

        Returns:
            Next node name to route to
        """
        review_stage = state.get("review_stage", "none")

        # Route based on review stage
        # 'none' -> completion check, 'completion' -> quality check, 'quality' -> security check
        # 'security' -> all checks done, 'final' -> aggregate results
        if review_stage in ("none", "completion", "quality"):
            return "quality_check"
        elif review_stage == "security":
            return "result_aggregation"
        else:
            return "result_aggregation"
