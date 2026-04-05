"""
Symbol query router.

Provides endpoints for searching and retrieving code symbols.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from graph_kb_api.dependencies import get_query_service
from graph_kb_api.schemas.symbols import (
    PathResponse,
    SymbolKind,
    SymbolResponse,
)

router = APIRouter(tags=["Symbols"])


@router.get("/repos/{repo_id}/symbols", response_model=List[SymbolResponse])
async def search_symbols(
    repo_id: str,
    pattern: Optional[str] = Query(None, description="Symbol name pattern (supports wildcards)"),
    kind: Optional[SymbolKind] = Query(None, description="Filter by symbol type"),
    file_pattern: Optional[str] = Query(None, description="Filter by file path pattern"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    query_service = Depends(get_query_service),
):
    """
    Search for symbols in a repository.

    Supports filtering by name pattern, symbol kind, and file path.
    """
    try:
        symbols = query_service.get_symbols_by_pattern(
            repo_id=repo_id,
            name_pattern=pattern,
            file_pattern=file_pattern,
            kind=kind.value if kind else None,
            limit=limit,
        )

        return [
            SymbolResponse(
                id=s.id,
                name=s.name,
                kind=SymbolKind(s.kind) if s.kind in SymbolKind._value2member_map_ else SymbolKind.FUNCTION,
                file_path=s.file_path,
                start_line=0,
                end_line=0,
                docstring=s.docstring,
                signature=None,
            )
            for s in symbols
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search symbols: {e}")


@router.get("/repos/{repo_id}/symbols/{symbol_id}", response_model=SymbolResponse)
async def get_symbol(
    repo_id: str,
    symbol_id: str,
    query_service = Depends(get_query_service),
):
    """
    Get details for a specific symbol.
    """
    try:
        symbol = query_service.get_symbol_by_id(symbol_id)

        if not symbol:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol_id} not found")

        return SymbolResponse(
            id=symbol.symbol_id,
            name=symbol.name,
            kind=SymbolKind(symbol.kind.value) if hasattr(symbol.kind, 'value') else SymbolKind(symbol.kind),
            file_path=symbol.file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            docstring=symbol.docstring,
            signature=symbol.signature,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get symbol: {e}")


@router.get("/repos/{repo_id}/symbols/{symbol_id}/neighbors", response_model=List[SymbolResponse])
async def get_symbol_neighbors(
    repo_id: str,
    symbol_id: str,
    direction: str = Query("both", pattern="^(incoming|outgoing|both)$"),
    edge_types: Optional[str] = Query(None, description="Comma-separated edge types"),
    limit: int = Query(50, ge=1, le=200),
    query_service = Depends(get_query_service),
):
    """
    Get symbols connected to a given symbol.

    - **incoming**: Symbols that call/reference this symbol
    - **outgoing**: Symbols that this symbol calls/references
    - **both**: All connected symbols
    """
    try:
        edge_type_list = edge_types.split(",") if edge_types else None

        neighbors = query_service.get_neighbors(
            symbol_id=symbol_id,
            direction=direction,
            edge_types=edge_type_list,
            limit=limit,
        )

        return [
            SymbolResponse(
                id=s.symbol_id,
                name=s.name,
                kind=SymbolKind(s.kind.value) if hasattr(s.kind, 'value') else SymbolKind(s.kind),
                file_path=s.file_path,
                start_line=s.start_line,
                end_line=s.end_line,
                docstring=s.docstring,
                signature=getattr(s, 'signature', None),
            )
            for s in neighbors
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get neighbors: {e}")


@router.get("/repos/{repo_id}/paths", response_model=PathResponse)
async def find_path(
    repo_id: str,
    from_symbol: str = Query(..., description="Source symbol ID"),
    to_symbol: str = Query(..., description="Target symbol ID"),
    max_hops: int = Query(5, ge=1, le=10, description="Maximum path length"),
    query_service = Depends(get_query_service),
):
    """
    Find the shortest path between two symbols.
    """
    try:
        path = query_service.find_path(
            from_symbol_id=from_symbol,
            to_symbol_id=to_symbol,
            max_hops=max_hops,
        )

        if not path:
            raise HTTPException(status_code=404, detail="No path found between symbols")

        path_responses = [
            SymbolResponse(
                id=s.symbol_id,
                name=s.name,
                kind=SymbolKind(s.kind.value) if hasattr(s.kind, 'value') else SymbolKind(s.kind),
                file_path=s.file_path,
                start_line=s.start_line,
                end_line=s.end_line,
                docstring=s.docstring,
                signature=getattr(s, 'signature', None),
            )
            for s in path
        ]

        return PathResponse(path=path_responses, path_length=len(path))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find path: {e}")
