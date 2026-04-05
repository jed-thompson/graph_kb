from unittest.mock import AsyncMock, MagicMock

import pytest

from graph_kb_api.database.repositories import DocumentRepository


@pytest.mark.asyncio
async def test_document_repository_list_accepts_collection_name_filter():
    session = AsyncMock()
    repo = DocumentRepository(session)

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    repo._execute = AsyncMock(return_value=result)

    documents = await repo.list(collection_name="specs")

    assert documents == []
    repo._execute.assert_awaited_once()

    query = repo._execute.await_args.args[0]
    where_clause = str(query.whereclause)
    assert "collection_name" in where_clause
