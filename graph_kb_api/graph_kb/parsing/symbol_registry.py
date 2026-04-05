"""Global symbol registry for cross-file symbol resolution.

This module provides the GlobalSymbolRegistry class that maintains mappings
from symbol names and IDs to graph node IDs, enabling cross-file relationship
resolution during Pass 2 of the two-pass indexing architecture.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from graph_kb_api.graph_kb.models.base import SymbolInfo
from graph_kb_api.graph_kb.models.enums import SymbolKind


@dataclass
class SymbolEntry:
    """Entry in the symbol registry containing symbol metadata.

    Attributes:
        symbol_id: Full symbol ID in format {file_path}:{name}:{kind}:{line}
        node_id: Graph node ID for this symbol
        name: Symbol name (for name-based lookups)
        file_path: File path where symbol is defined
        kind: Symbol kind (function, class, etc.)
    """
    symbol_id: str
    node_id: str
    name: str
    file_path: str
    kind: SymbolKind


class GlobalSymbolRegistry:
    """Global registry for cross-file symbol resolution.

    Maintains multiple indexes for efficient symbol lookup:
    - symbol_id → node_id (direct lookup)
    - name → list of symbol_ids (name-based lookup with disambiguation)
    - file_path → list of symbol_ids (file-based lookup)
    - module_path → file_path (module resolution)
    """

    def __init__(self) -> None:
        """Initialize the registry with empty indexes."""
        # Primary index: symbol_id → node_id
        self._symbol_id_to_node: Dict[str, str] = {}

        # Secondary index: symbol_id → full entry (for filtering)
        self._symbol_entries: Dict[str, SymbolEntry] = {}

        # Name-based index: name → list of symbol_ids
        self._name_to_symbols: Dict[str, List[str]] = {}

        # File-based index: file_path → list of symbol_ids
        self._file_to_symbols: Dict[str, List[str]] = {}

        # Module resolution: module_path → file_path
        self._module_to_file: Dict[str, str] = {}

    def register_symbol(self, symbol: SymbolInfo, node_id: str) -> None:
        """Register a symbol for cross-file lookup.

        Args:
            symbol: SymbolInfo object containing symbol metadata
            node_id: Graph node ID for this symbol
        """
        symbol_id = symbol.symbol_id

        # Create entry
        entry = SymbolEntry(
            symbol_id=symbol_id,
            node_id=node_id,
            name=symbol.name,
            file_path=symbol.file_path,
            kind=symbol.kind,
        )

        # Primary index
        self._symbol_id_to_node[symbol_id] = node_id
        self._symbol_entries[symbol_id] = entry

        # Name-based index
        if symbol.name not in self._name_to_symbols:
            self._name_to_symbols[symbol.name] = []
        self._name_to_symbols[symbol.name].append(symbol_id)

        # File-based index
        if symbol.file_path not in self._file_to_symbols:
            self._file_to_symbols[symbol.file_path] = []
        self._file_to_symbols[symbol.file_path].append(symbol_id)

    def register_module(self, module_path: str, file_path: str) -> None:
        """Register module → file mapping.

        Args:
            module_path: Module import path (e.g., "utils.auth")
            file_path: Corresponding file path (e.g., "utils/auth.py")
        """
        self._module_to_file[module_path] = file_path

    def resolve_symbol(
        self,
        name: str,
        target_file: Optional[str] = None,
        kind: Optional[SymbolKind] = None,
    ) -> Optional[str]:
        """Resolve symbol name to node_id with optional filtering.

        Args:
            name: Symbol name to resolve
            target_file: Optional file path to filter by
            kind: Optional symbol kind to filter by

        Returns:
            Graph node ID if found and unambiguous, None otherwise
        """
        # Get all symbol_ids with this name
        symbol_ids = self._name_to_symbols.get(name, [])

        if not symbol_ids:
            return None

        # Apply filters
        candidates: List[SymbolEntry] = []
        for symbol_id in symbol_ids:
            entry = self._symbol_entries.get(symbol_id)
            if entry is None:
                continue

            # Filter by file path if specified
            if target_file is not None and entry.file_path != target_file:
                continue

            # Filter by kind if specified
            if kind is not None and entry.kind != kind:
                continue

            candidates.append(entry)

        # Return node_id if exactly one match
        if len(candidates) == 1:
            return candidates[0].node_id

        # If multiple matches and no filters provided, return None (ambiguous)
        # If multiple matches with filters, still ambiguous
        if len(candidates) > 1:
            return None

        return None

    def get_node_id(self, symbol_id: str) -> Optional[str]:
        """Direct lookup by symbol_id.

        Args:
            symbol_id: Full symbol ID in format {file_path}:{name}:{kind}:{line}

        Returns:
            Graph node ID if found, None otherwise
        """
        return self._symbol_id_to_node.get(symbol_id)

    def get_file_for_module(self, module_path: str) -> Optional[str]:
        """Get file path for module.

        Args:
            module_path: Module import path (e.g., "utils.auth")

        Returns:
            File path if found, None otherwise
        """
        return self._module_to_file.get(module_path)

    def get_symbols_in_file(self, file_path: str) -> List[str]:
        """Get all symbol IDs defined in a file.

        Args:
            file_path: File path to look up

        Returns:
            List of symbol IDs defined in the file
        """
        return self._file_to_symbols.get(file_path, [])

    def get_symbols_by_name(self, name: str) -> List[str]:
        """Get all symbol IDs with a given name.

        Args:
            name: Symbol name to look up

        Returns:
            List of symbol IDs with this name
        """
        return self._name_to_symbols.get(name, [])

    @property
    def symbol_count(self) -> int:
        """Get total number of registered symbols."""
        return len(self._symbol_id_to_node)

    @property
    def module_count(self) -> int:
        """Get total number of registered modules."""
        return len(self._module_to_file)
