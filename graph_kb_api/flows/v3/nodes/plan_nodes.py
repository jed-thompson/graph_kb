"""Barrel re-exports for plan workflow nodes.

.. deprecated::
    This module is deprecated. Import directly from
    ``graph_kb_api.flows.v3.nodes.plan.<module>`` instead.
    This file will be removed in a future release.

All nodes moved to the plan/ sub-package. This file preserves backward compatibility
so existing imports (e.g. ``from graph_kb_api.flows.v3.nodes.plan_nodes import ...``)
continue to work without changes.
"""

import warnings

warnings.warn(
    "plan_nodes.py is deprecated. Import directly from "
    "graph_kb_api.flows.v3.nodes.plan.<module> instead. "
    "This barrel file will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from graph_kb_api.flows.v3.nodes.plan import (  # noqa: F401
    AggregateNode,
    AlignNode,
    AssembleNode,
    AssemblyApprovalNode,
    AssignNode,
    BudgetCheckNode,
    CollectContextNode,
    # Assembly phase
    CompletenessNode,
    CompositionReviewNode,
    ConfidenceGateNode,
    ConsistencyNode,
    CritiqueNode,
    DecomposeNode,
    DeepAnalysisNode,
    DispatchNode,
    DispatchResearchNode,
    FeasibilityNode,
    FeedbackReviewNode,
    FetchContextNode,
    FinalizeNode,
    # Research phase
    FormulateQueriesNode,
    GapCheckNode,
    GapNode,
    GenerateNode,
    PlanningApprovalNode,
    PRESERVE_AFTER_ORCHESTRATE,
    PRESERVE_AFTER_RESEARCH,
    ProgressNode,
    PruneAfterOrchestrateNode,
    # Orchestrate phase
    PruneAfterResearchNode,
    ResearchApprovalNode,
    ReviewNode,
    # Planning phase
    RoadmapNode,
    TaskContextInputNode,
    TaskResearchNode,
    TaskSelectorNode,
    TemplateNode,
    ToolPlanNode,
    # Context phase
    ValidateContextNode,
    ValidateDagNode,
    ValidateNode,
    WorkerNode,
)

__all__ = [
    # Context phase
    "ValidateContextNode",
    "CollectContextNode",
    "ReviewNode",
    "DeepAnalysisNode",
    "FeedbackReviewNode",
    # Research phase
    "FormulateQueriesNode",
    "DispatchResearchNode",
    "AggregateNode",
    "GapCheckNode",
    "ConfidenceGateNode",
    "ResearchApprovalNode",
    # Planning phase
    "RoadmapNode",
    "FeasibilityNode",
    "DecomposeNode",
    "ValidateDagNode",
    "AssignNode",
    "AlignNode",
    "PlanningApprovalNode",
    # Orchestrate phase
    "PRESERVE_AFTER_RESEARCH",
    "PRESERVE_AFTER_ORCHESTRATE",
    "PruneAfterResearchNode",
    "PruneAfterOrchestrateNode",
    "BudgetCheckNode",
    "TaskSelectorNode",
    "FetchContextNode",
    "GapNode",
    "TaskResearchNode",
    "ToolPlanNode",
    "DispatchNode",
    "WorkerNode",
    "CritiqueNode",
    "ProgressNode",
    # Assembly phase
    "CompletenessNode",
    "CompositionReviewNode",
    "TemplateNode",
    "GenerateNode",
    "ConsistencyNode",
    "AssembleNode",
    "ValidateNode",
    "AssemblyApprovalNode",
    "FinalizeNode",
]
