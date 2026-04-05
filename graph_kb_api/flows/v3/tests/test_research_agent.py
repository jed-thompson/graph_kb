"""Focused tests for ResearchAgent document lookup behavior."""

from types import SimpleNamespace

import pytest

from graph_kb_api.flows.v3.agents.research_agent import ResearchAgent
from graph_kb_api.graph_kb.models.base import DocumentMetadata
from graph_kb_api.graph_kb.models.enums import DocumentStatus


class FakeMetadataStore:
    def __init__(self, docs):
        self.docs = docs
        self.calls: list[dict] = []

    def list_documents(self, **kwargs):
        self.calls.append(kwargs)
        return self.docs


@pytest.mark.asyncio
async def test_search_specs_normalizes_document_metadata_and_scopes_queries():
    docs = [
        DocumentMetadata(
            doc_id="doc-1",
            original_name="Checkout Spec.md",
            file_path="docs/checkout-spec.md",
            parent_name="repo-123",
            category="technical-specs",
            collection_name="repo-123/technical-specs",
            status=DocumentStatus.COMPLETED,
        ),
        {
            "doc_id": "doc-2",
            "original_name": "Payments API Contract.md",
            "file_path": "docs/payments-api.md",
            "parent_name": "repo-123",
            "category": "api-reference",
            "collection_name": "repo-123/support",
            "status": "completed",
        },
    ]
    metadata_store = FakeMetadataStore(docs)
    graph_store = SimpleNamespace(metadata_store=metadata_store)

    agent = ResearchAgent()
    results = await agent._search_specs("checkout payments", graph_store, repo_id="repo-123")

    assert [call["parent_name"] for call in metadata_store.calls] == ["repo-123"]
    assert any(result["name"] == "Checkout Spec.md" for result in results)
    assert any(result["file_path"] == "docs/checkout-spec.md" for result in results)


@pytest.mark.asyncio
async def test_search_api_docs_requires_workflow_scope():
    metadata_store = FakeMetadataStore(
        [
            {
                "doc_id": "doc-1",
                "original_name": "Unscoped API.md",
                "file_path": "docs/api.md",
                "category": "api-reference",
                "status": "completed",
            }
        ]
    )
    graph_store = SimpleNamespace(metadata_store=metadata_store)

    agent = ResearchAgent()
    results = await agent._search_api_docs("payments api", graph_store)

    assert results == []
    assert metadata_store.calls == []
