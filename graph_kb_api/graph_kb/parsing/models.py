"""Parsing-related data models.

This module contains data models specific to language parsing operations,
including AST parsing, symbol extraction, and cross-file resolution.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SymbolType(Enum):
    """Types of symbols that can be extracted from code."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    MODULE = "module"
    PROPERTY = "property"
    DECORATOR = "decorator"
    INTERFACE = "interface"
    ENUM = "enum"
    TYPE_ALIAS = "type_alias"


class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    CPP = "cpp"
    C = "c"
    CSHARP = "csharp"
    UNKNOWN = "unknown"


@dataclass
class ParseResult:
    """Result of parsing a source code file."""
    file_path: str
    language: Language
    ast: Any
    success: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parse_time: float = 0.0


@dataclass
class SymbolInfo:
    """Information about a code symbol."""
    id: str
    name: str
    type: SymbolType
    file_path: str
    line_number: int
    column_number: int
    end_line_number: Optional[int] = None
    end_column_number: Optional[int] = None
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)  # public, private, static, etc.
    parent_symbol: Optional[str] = None  # For methods, nested classes, etc.
    namespace: Optional[str] = None
    signature: Optional[str] = None
    complexity: Optional[int] = None


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module_path: str
    imported_names: List[str]
    alias: Optional[str] = None
    is_relative: bool = False
    line_number: int = 0
    import_type: str = "import"  # import, from_import, require, etc.


@dataclass
class RelationshipInfo:
    """Information about a relationship between symbols."""
    from_symbol_id: str
    to_symbol_id: Optional[str]
    to_symbol_name: Optional[str]
    to_module_path: Optional[str]
    relationship_type: str  # calls, extends, implements, uses, etc.
    line_number: int
    confidence: float = 1.0
    context: Optional[str] = None
    is_resolved: bool = False
    is_external: bool = False


@dataclass
class ExtractionResult:
    """Result of symbol extraction from parsed code."""
    file_path: str
    language: Language
    symbols: List[SymbolInfo]
    imports: List[ImportInfo]
    relationships: List[RelationshipInfo]
    extraction_time: float = 0.0
    errors: List[str] = field(default_factory=list)


@dataclass
class ModuleResolution:
    """Result of module path resolution."""
    module_path: str
    resolved_file_path: Optional[str]
    is_external: bool
    is_builtin: bool
    resolution_method: str  # "direct", "package", "relative", etc.
    confidence: float = 1.0


@dataclass
class SymbolRegistry:
    """Registry of symbols for cross-file resolution."""
    symbols_by_name: Dict[str, List[SymbolInfo]] = field(default_factory=dict)
    symbols_by_file: Dict[str, List[SymbolInfo]] = field(default_factory=dict)
    symbols_by_id: Dict[str, SymbolInfo] = field(default_factory=dict)
    unresolved_references: List[RelationshipInfo] = field(default_factory=list)


@dataclass
class ParsingConfig:
    """Configuration for parsing operations."""
    max_file_size: int = 1024 * 1024  # 1MB
    timeout: float = 30.0  # seconds
    extract_docstrings: bool = True
    extract_comments: bool = False
    extract_decorators: bool = True
    calculate_complexity: bool = False
    resolve_imports: bool = True
    follow_inheritance: bool = True


@dataclass
class ParsingStats:
    """Statistics from parsing operations."""
    total_files: int
    parsed_files: int
    failed_files: int
    total_symbols: int
    symbols_by_type: Dict[SymbolType, int] = field(default_factory=dict)
    languages_detected: Dict[Language, int] = field(default_factory=dict)
    total_parse_time: float = 0.0
    average_parse_time: float = 0.0
