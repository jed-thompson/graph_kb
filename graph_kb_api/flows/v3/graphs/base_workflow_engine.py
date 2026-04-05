"""
Base workflow engine for LangGraph-based workflows.

This module provides an abstract base class that defines the common interface
and behavior for all workflow engines in the v3 framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, RunnableConfig

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.checkpointer import CheckpointerFactory
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class BaseWorkflowEngine(ABC):
    """
    Abstract base class for all workflow engines.

    This class defines the common interface and lifecycle management for
    LangGraph-based workflows including:
    - Tool initialization and binding
    - Node instantiation
    - Graph compilation with checkpointing
    - Service injection
    - Workflow execution and resumption

    Subclasses must implement:
    - _initialize_tools(): Return list of tools for the workflow
    - _initialize_nodes(): Create and store node instances
    - _compile_workflow(): Build and compile the workflow graph
    """

    def __init__(
        self,
        workflow_context: WorkflowContext,
        max_iterations: int = 5,
        workflow_name: str = "workflow",
        use_default_checkpointer: bool = True,
    ):
        """
        Initialize the workflow engine.

        Args:
            workflow_context: Container with all workflow dependencies (LLM,
                services, checkpointer, etc.)
            max_iterations: Maximum number of tool calling iterations
            workflow_name: Name of the workflow for logging
            use_default_checkpointer: If True and no checkpointer in context,
                create default. If False, respect None as "no checkpointing".
        """
        self.workflow_context: WorkflowContext = workflow_context
        self.llm: LLMService = workflow_context.require_llm
        self.max_iterations: int = max_iterations
        self.workflow_name: str = workflow_name

        # Initialize checkpointer from context or create default
        if workflow_context.checkpointer is not None:
            self.checkpointer: Optional[BaseCheckpointSaver] = workflow_context.checkpointer
        elif use_default_checkpointer:
            self.checkpointer = CheckpointerFactory.create_checkpointer()
        else:
            self.checkpointer = None

        # Initialize tools (subclass responsibility)
        self.tools = self._initialize_tools()

        # Initialize nodes (subclass responsibility)
        self._initialize_nodes()

        # Compile workflow (done once)
        self.compiled_workflow = self._compile_workflow()

        checkpointer_info = (
            "None (no checkpointing)"
            if self.checkpointer is None
            else CheckpointerFactory.get_checkpointer_info()["type"]
        )

        logger.info(
            f"{self.workflow_name} engine initialized",
            data={
                "workflow_name": self.workflow_name,
                "tool_count": len(self.tools),
                "max_iterations": self.max_iterations,
                "checkpointer_type": checkpointer_info,
            },
        )

    @property
    def app_context(self) -> Any:
        """Backward-compatible access to AppContext."""
        return self.workflow_context.app_context

    @property
    def artifact_service(self) -> Any:
        """Access artifact service from workflow context."""
        return self.workflow_context.artifact_service

    @property
    def blob_storage(self) -> Any:
        """Access blob storage from workflow context."""
        return self.workflow_context.blob_storage

    @property
    def workflow(self) -> CompiledStateGraph:
        """Get the compiled workflow graph."""
        return self.compiled_workflow

    @abstractmethod
    def _initialize_tools(self) -> List[Any]:
        """
        Initialize all tools for the workflow.

        Returns:
            List of tool functions/objects
        """
        pass

    @abstractmethod
    def _initialize_nodes(self) -> None:
        """
        Initialize all node instances.

        Subclasses should create and store node instances as instance variables.
        Example:
            self.validate_node = ValidateInputNode()
            self.process_node = ProcessNode()
        """
        pass

    @abstractmethod
    def _compile_workflow(self) -> CompiledStateGraph:
        """
        Compile the workflow graph.

        This method should:
        1. Create a StateGraph with appropriate state type
        2. Add all nodes
        3. Add edges and conditional routing
        4. Compile with checkpointer

        Returns:
            Compiled StateGraph ready for execution
        """
        pass

    async def start_workflow(
        self,
        user_query: str,
        user_id: str,
        session_id: str,
        config: Optional[RunnableConfig] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Start a new workflow execution (non-streaming).

        Note: When using checkpointing, prefer start_workflow_stream() to avoid
        MESSAGE_COERCION_FAILURE errors from LangGraph's Overwrite objects.

        Args:
            user_query: User's input query
            user_id: User identifier
            session_id: Session identifier
            config: Optional LangGraph configuration
            **kwargs: Additional workflow-specific parameters

        Returns:
            Dict containing workflow results

        Warning:
            When using checkpointing, the result may contain LangGraph Overwrite
            objects in the 'messages' field, which can cause MESSAGE_COERCION_FAILURE
            errors when accessed. Use start_workflow_stream() instead for checkpointed
            workflows.
        """
        # Create initial state (subclasses can override _create_initial_state)
        initial_state = self._create_initial_state(
            user_query=user_query, user_id=user_id, session_id=session_id, **kwargs
        )

        logger.info(
            f"Starting {self.workflow_name} workflow",
            data={
                "user_id": user_id,
                "session_id": session_id,
                "query_length": len(user_query),
                "user_query_param": user_query[:100],
                "initial_state_has_user_query": "user_query" in initial_state,
                "initial_state_user_query": initial_state.get("user_query", "NOT_SET")[:100]
                if initial_state.get("user_query")
                else "EMPTY",
                "checkpointer_is_none": self.checkpointer is None,
            },
        )

        # Execute workflow
        result = await self.compiled_workflow.ainvoke(initial_state, config=config)

        logger.info(
            f"{self.workflow_name} workflow completed",
            data={
                "user_id": user_id,
                "session_id": session_id,
                "iterations": result.get("agent_iterations", 0),
            },
        )

        return result

    async def start_workflow_stream(
        self,
        user_query: str,
        user_id: str,
        session_id: str,
        config: Optional[RunnableConfig] = None,
        stream_mode: Literal["values", "updates", "messages"] = "updates",
        **kwargs,
    ):
        """
        Start workflow with streaming execution.

        Recommended for checkpointed workflows. This method streams workflow
        execution and should be used when:
        - Using checkpointing for conversation continuity
        - Wanting real-time progress updates
        - Following Chainlit + LangGraph best practices
        - Avoiding MESSAGE_COERCION_FAILURE errors

        The streaming pattern aligns with Chainlit + LangGraph integration guidelines
        and avoids issues with Overwrite objects in checkpointed state.

        Args:
            user_query: User's input query
            user_id: User identifier
            session_id: Session identifier
            config: Optional LangGraph config with thread-id for continuity
            stream_mode: Streaming mode - "updates", "messages", or "values"
                - "updates": Yields {node_name: state_update} for each node
                - "messages": Yields individual messages as they're generated
                - "values": Yields complete state after each node
            **kwargs: Additional workflow-specific parameters

        Yields:
            Workflow state updates as they occur. Format depends on stream_mode:
            - "updates": Dict[str, Any] with node name as key
            - "messages": Tuple[BaseMessage, Dict] with message and metadata
            - "values": Complete state dict

        Note:
            When using streaming, nodes should send responses directly to the user
            (e.g., via PresentToUserNode in Chainlit). Don't try to access a final
            result dictionary as it may contain Overwrite objects.

        See Also:
            - Chainlit + LangGraph docs: https://docs.chainlit.io/integrations/langchain
            - LangGraph streaming: https://docs.langchain.com/oss/python/langgraph/streaming
        """
        # Create initial state
        initial_state = self._create_initial_state(
            user_query=user_query, user_id=user_id, session_id=session_id, **kwargs
        )

        logger.info(
            f"Starting {self.workflow_name} workflow (streaming)",
            data={
                "user_id": user_id,
                "session_id": session_id,
                "stream_mode": stream_mode,
                "query_length": len(user_query),
                "has_checkpointer": self.checkpointer is not None,
            },
        )

        # Stream workflow execution
        async for chunk in self.compiled_workflow.astream(initial_state, config=config, stream_mode=stream_mode):
            yield chunk

        logger.info(
            f"{self.workflow_name} workflow completed (streaming)",
            data={"user_id": user_id, "session_id": session_id},
        )

    def _create_initial_state(self, user_query: str, user_id: str, session_id: str, **kwargs) -> Dict[str, Any]:
        """
        Create initial workflow state.

        Subclasses can override this to customize initial state structure.

        Args:
            user_query: User's input query
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
            **kwargs,
        }

    async def _cancel_stale_interrupts(
        self,
        config: RunnableConfig,
        *,
        preserve_interrupt_id: str | None = None,
    ) -> int:
        """Cancel all but the most recent pending interrupt.

        When a workflow has multiple pending interrupts (e.g. from subgraph
        navigation or phase restarts), LangGraph raises RuntimeError on
        resume.  This method cancels stale interrupts so that
        ``Command(resume=...)`` succeeds.

        Args:
            config: LangGraph configuration with thread_id.

        Returns:
            Number of stale interrupts that were cancelled.
        """
        try:
            snapshot = await self.compiled_workflow.aget_state(config)
            if not snapshot or not snapshot.tasks:
                return 0

            tasks_with_interrupts = [task for task in snapshot.tasks if getattr(task, "interrupts", None)]

            if len(tasks_with_interrupts) <= 1:
                return 0

            preserved_task_id: str | None = None
            if preserve_interrupt_id:
                for task in tasks_with_interrupts:
                    interrupts = getattr(task, "interrupts", None) or []
                    if any(getattr(interrupt, "id", None) == preserve_interrupt_id for interrupt in interrupts):
                        preserved_task_id = getattr(task, "id", None)
                        break

            # Cancel all but the preserved task (when specified), otherwise keep
            # only the most recent interrupt by task order.
            cancelled = 0
            if preserved_task_id is not None:
                stale_tasks = [task for task in tasks_with_interrupts if getattr(task, "id", None) != preserved_task_id]
            else:
                stale_tasks = tasks_with_interrupts[:-1]

            for task in stale_tasks:
                await self.compiled_workflow.aupdate_state(
                    config,
                    None,
                    task_id=task.id,
                )
                cancelled += 1
                logger.info(
                    f"Cancelled stale interrupt on task '{task.id}' (node '{task.name}')",
                    data={"workflow_name": self.workflow_name},
                )

            if cancelled:
                logger.info(
                    f"Cancelled {cancelled} stale interrupt(s) before resume",
                    data={"workflow_name": self.workflow_name},
                )
            return cancelled
        except Exception:
            logger.warning(
                "Failed to cancel stale interrupts (non-fatal)",
                exc_info=True,
            )
            return 0

    async def resume_workflow(
        self,
        workflow_id: str,
        user_id: str,
        input_data: Optional[Dict[str, Any]] = None,
        config: Optional[RunnableConfig] = None,
        *,
        interrupt_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Resume an interrupted workflow using Command(resume=...).

        This uses LangGraph's native interrupt/resume mechanism rather than
        re-invoking the full graph with patched state. The Command(resume=...)
        pattern delivers the user's input directly to the interrupt() call
        that paused the graph, allowing execution to continue from exactly
        where it left off.

        Before resuming, any stale pending interrupts (e.g. left over from
        subgraph navigation or phase restarts) are automatically cancelled
        so that LangGraph's single-interrupt requirement is satisfied.

        Args:
            workflow_id: Workflow identifier
            user_id: User identifier
            input_data: User-supplied data to resume the interrupted node
            config: LangGraph configuration (must include thread_id)

        Returns:
            Dict containing workflow results or state at next interrupt
        """
        logger.info(
            f"Resuming {self.workflow_name} workflow via Command(resume=...)",
            data={"workflow_id": workflow_id, "user_id": user_id},
        )

        # Cancel stale interrupts to avoid:
        #   RuntimeError: When there are multiple pending interrupts, you
        #   must specify the interrupt id when resuming.
        if config is not None and interrupt_id is None:
            await self._cancel_stale_interrupts(config)

        resume_payload: dict[str, Any] | Any = input_data or {}
        if interrupt_id:
            resume_payload = {interrupt_id: input_data or {}}

        command = Command(resume=resume_payload)
        result = await self.compiled_workflow.ainvoke(command, config=config)

        logger.info(
            f"{self.workflow_name} workflow resumed successfully",
            data={"workflow_id": workflow_id, "user_id": user_id},
        )

        return result

    async def get_workflow_state(self, config: Optional[RunnableConfig] = None) -> Optional[Dict[str, Any]]:
        """
        Get current workflow state.

        Args:
            config: Optional LangGraph configuration

        Returns:
            Current state dictionary or None if not found
        """
        if config is None:
            return None
        state_snapshot = await self.compiled_workflow.aget_state(config)
        return state_snapshot.values if state_snapshot else None

    def get_config_with_services(self, config: Optional[RunnableConfig] = None) -> RunnableConfig:
        """Inject workflow services into a LangGraph RunnableConfig.

        Ensures ``config["configurable"]`` contains ``artifact_service`` and
        ``llm`` from the workflow context so that downstream nodes can access
        them via ``ThreadConfigurable``.

        Args:
            config: Existing config dict to augment, or ``None`` to create one.

        Returns:
            The (possibly new) config dict with services injected.
        """
        if config is None:
            config = {}
        configurable = config.setdefault("configurable", {})
        configurable["artifact_service"] = self.artifact_service
        configurable["llm"] = self.llm
        configurable["context"] = self.workflow_context
        return config

    def get_workflow_info(self) -> Dict[str, Any]:
        """
        Get information about the workflow engine.

        Returns:
            Dict with workflow metadata
        """
        return {
            "workflow_name": self.workflow_name,
            "tool_count": len(self.tools),
            "max_iterations": self.max_iterations,
            "checkpointer_type": CheckpointerFactory.get_checkpointer_info()["type"],
        }
