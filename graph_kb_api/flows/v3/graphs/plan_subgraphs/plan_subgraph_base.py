"""PlanSubgraph — shared base class for the 5 plan phase subgraphs.

Consolidates the identical ``__init__`` and ``_initialize_tools`` logic that
was previously duplicated across ContextSubgraph, ResearchSubgraph,
PlanningSubgraph, OrchestrateSubgraph, and AssemblySubgraph.

Subclasses implement only ``_initialize_nodes()`` and ``_compile_workflow()``.
"""

from __future__ import annotations

from abc import abstractmethod

from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext


class PlanSubgraph(BaseWorkflowEngine):
    """Base class for the 5 plan phase subgraphs.

    Consolidates shared ``__init__`` and ``_initialize_tools`` logic.
    Subclasses implement ``_initialize_nodes()`` and ``_compile_workflow()``.
    """

    def __init__(
        self,
        workflow_context: WorkflowContext,
        workflow_name: str,
    ) -> None:
        super().__init__(
            workflow_context=workflow_context,
            max_iterations=1,
            workflow_name=workflow_name,
            use_default_checkpointer=False,
        )

    def _initialize_tools(self) -> list:
        """No standalone tools — nodes handle their own tooling."""
        return []

    @abstractmethod
    def _initialize_nodes(self) -> None: ...

    @abstractmethod
    def _compile_workflow(self) -> CompiledStateGraph: ...


__all__ = ["PlanSubgraph"]
