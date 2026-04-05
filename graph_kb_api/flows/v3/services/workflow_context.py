"""Workflow context service container for LangGraph nodes and agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

if TYPE_CHECKING:
    from graph_kb_api.context import AppContext
    from graph_kb_api.core.llm import LLMService
    from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
    from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
    from graph_kb_api.graph_kb.facade import GraphKBFacade
    from graph_kb_api.graph_kb.storage.vector_store import ChromaVectorStore
    from graph_kb_api.storage.blob_storage import BlobStorage


@dataclass
class WorkflowContext:
    """Type-safe service container for LangGraph nodes and agents.

    Consolidates all workflow-scoped dependencies into a single container,
    avoiding parameter sprawl in engine constructors.

    Attributes:
        llm: LLMService (extends BaseChatModel with retry logic).
        app_context: Application context singleton for settings and services.
        vector_store: Optional vector store for embeddings.
        artifact_service: Service for managing workflow artifacts.
        graph_store: GraphKB facade for graph operations.
        blob_storage: Storage for spec blobs and large objects.
        checkpointer: LangGraph checkpointer for state persistence.
        fingerprint_tracker: Tracks content fingerprints for change detection.
    """

    llm: Optional[LLMService] = None
    app_context: Optional[AppContext] = None
    vector_store: Optional[ChromaVectorStore] = None
    artifact_service: Optional[ArtifactService] = None
    graph_store: Optional[GraphKBFacade] = None
    blob_storage: Optional[BlobStorage] = None
    checkpointer: Optional[BaseCheckpointSaver] = None
    fingerprint_tracker: Optional[FingerprintTracker] = field(default=None, repr=False)

    @property
    def require_llm(self) -> LLMService:
        """Return the LLM service, raising if not configured.

        Use this in agents that require LLM (mandatory dependency).
        Agents with graceful fallbacks should use ``self.llm`` directly.
        """
        llm: LLMService | None = self.llm
        if llm is None:
            raise RuntimeError(
                "WorkflowContext.llm is required but not configured. "
                "Ensure the engine is initialized with an LLM service."
            )
        return llm

    @classmethod
    def from_app_context(
        cls,
        app_context: AppContext,
        artifact_service: Optional[ArtifactService] = None,
        blob_storage: Optional[BlobStorage] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ) -> WorkflowContext:
        """Create WorkflowContext from the legacy global AppContext.

        Uses LLMService directly since it now extends BaseChatModel,
        preserving retry logic and hot-swap capability.

        Args:
            app_context: The application context singleton.
            artifact_service: Optional artifact service (created if not provided).
            blob_storage: Optional blob storage for specs.
            checkpointer: Optional checkpointer (uses AppContext's if not provided).

        Returns:
            Configured WorkflowContext instance.
        """
        llm = getattr(app_context, "llm", None)
        if llm is None:
            raise ValueError("AppContext must have an 'llm' attribute")

        return cls(
            llm=llm,  # LLMService is now a BaseChatModel
            app_context=app_context,
            vector_store=getattr(app_context, "vector_store", None),
            artifact_service=artifact_service or getattr(app_context, "artifact_service", None),
            graph_store=getattr(app_context, "graph_kb_facade", None),
            blob_storage=blob_storage,
            checkpointer=checkpointer or getattr(app_context, "checkpointer", None),
        )
