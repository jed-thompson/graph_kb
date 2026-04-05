"""Enhanced symbol extraction from parsed source code (V2).

This module handles extracting code symbols (functions, classes, methods, etc.)
and their relationships (calls, imports, inheritance) from AST trees with
rich metadata for graph knowledge base construction.

V2 enhancements:
- Symbol IDs include line numbers for disambiguation
- Relationships include cross-file resolution metadata
- Intra-file relationships are resolved immediately
- Cross-file relationships are deferred for Pass 2 resolution
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from tree_sitter import Node, Tree

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.base import ParameterInfo, Relationship, SymbolInfo
from ..models.enums import Language, RelationshipType, SymbolKind, Visibility

# Import directly from module to avoid circular import through ingestion/__init__.py
from .language_parser import LanguageParser

logger = EnhancedLogger(__name__)


class SymbolExtractor(ABC):
    """Abstract base class for symbol extraction from parsed source code.

    This interface defines the contract for extracting symbols and relationships
    from Abstract Syntax Trees.
    """

    @abstractmethod
    def extract_symbols(
        self,
        tree: Tree,
        file_path: str,
        language: Language,
        content: str,
    ) -> List[SymbolInfo]:
        """Extract all symbols from an AST.

        Args:
            tree: Parsed AST tree.
            file_path: Path to the source file.
            language: Programming language.
            content: Source code content.

        Returns:
            List of extracted symbols.
        """
        pass

    @abstractmethod
    def extract_relationships(
        self,
        tree: Tree,
        symbols: List[SymbolInfo],
        language: Language,
        content: str,
        file_path: str,
    ) -> List[Relationship]:
        """Extract relationships between symbols.

        Args:
            tree: Parsed AST tree.
            symbols: Previously extracted symbols.
            language: Programming language.
            content: Source code content.
            file_path: Path to the source file.

        Returns:
            List of relationships between symbols.
        """
        pass

    @abstractmethod
    def extract_all(
        self,
        tree: Tree,
        file_path: str,
        language: Language,
        content: str,
    ) -> Tuple[List[SymbolInfo], List[Relationship]]:
        """Extract both symbols and relationships.

        Args:
            tree: Parsed AST tree.
            file_path: Path to the source file.
            language: Programming language.
            content: Source code content.

        Returns:
            Tuple of (symbols, relationships).
        """
        pass


class SymbolExtractorV2(SymbolExtractor):
    """Extracts symbols and relationships from parsed source code (V2).

    Enhanced to capture:
    - Function signatures, parameters, return types
    - Decorators and their targets
    - Class inheritance and interface implementation
    - Variable/constant references (USES relationships)
    - Cyclomatic complexity estimates
    - Cross-file resolution metadata for relationships
    """
    """Extracts symbols and relationships from parsed source code (V2).

    Enhanced to capture:
    - Function signatures, parameters, return types
    - Decorators and their targets
    - Class inheritance and interface implementation
    - Variable/constant references (USES relationships)
    - Cyclomatic complexity estimates
    - Cross-file resolution metadata for relationships
    """

    def __init__(self, parser: Optional[LanguageParser] = None):
        from .language_parser import TreeSitterLanguageParser
        self.parser = parser or TreeSitterLanguageParser()
        self._extractors: Dict[Language, "BaseLanguageExtractorV2"] = {
            Language.PYTHON: PythonExtractorV2(),
            Language.JAVASCRIPT: JavaScriptExtractorV2(),
            Language.TYPESCRIPT: TypeScriptExtractorV2(),
        }

    def extract_symbols(
        self,
        tree: Tree,
        file_path: str,
        language: Language,
        content: str,
    ) -> List[SymbolInfo]:
        """Extract all symbols from an AST with enhanced metadata."""
        extractor = self._extractors.get(language)
        if not extractor:
            logger.debug(f"No symbol extractor for {language.value}")
            return []
        return extractor.extract_symbols(tree, file_path, content)

    def extract_relationships(
        self,
        tree: Tree,
        symbols: List[SymbolInfo],
        language: Language,
        content: str,
        file_path: str,
    ) -> List[Relationship]:
        """Extract relationships between symbols with cross-file resolution metadata."""
        extractor = self._extractors.get(language)
        if not extractor:
            return []
        return extractor.extract_relationships(tree, symbols, content, file_path)

    def extract_all(
        self,
        tree: Tree,
        file_path: str,
        language: Language,
        content: str,
    ) -> Tuple[List[SymbolInfo], List[Relationship]]:
        """Extract both symbols and relationships."""
        symbols = self.extract_symbols(tree, file_path, language, content)
        relationships = self.extract_relationships(tree, symbols, language, content, file_path)
        return symbols, relationships


class BaseLanguageExtractorV2:
    """Base class for language-specific symbol extractors (V2)."""

    def extract_symbols(
        self, tree: Tree, file_path: str, content: str
    ) -> List[SymbolInfo]:
        raise NotImplementedError

    def extract_relationships(
        self, tree: Tree, symbols: List[SymbolInfo], content: str, file_path: str
    ) -> List[Relationship]:
        raise NotImplementedError

    def _get_node_text(self, node: Node, content: bytes) -> str:
        return content[node.start_byte:node.end_byte].decode("utf-8")

    def _create_symbol_id(self, file_path: str, name: str, kind: SymbolKind, line: int) -> str:
        """Create a unique symbol ID including line number for disambiguation.

        Format: {file_path}:{name}:{kind}:{line}

        Args:
            file_path: Path to the file containing the symbol
            name: Name of the symbol
            kind: SymbolKind enum value
            line: Line number (1-indexed) where the symbol is defined

        Returns:
            A unique symbol ID string
        """
        return f"{file_path}:{name}:{kind.value}:{line}"

    def _find_nodes_by_type(self, node: Node, node_type: str) -> List[Node]:
        results = []
        if node.type == node_type:
            results.append(node)
        for child in node.children:
            results.extend(self._find_nodes_by_type(child, node_type))
        return results

    def _find_child_by_type(self, node: Node, node_type: str) -> Optional[Node]:
        for child in node.children:
            if child.type == node_type:
                return child
        return None

    def _find_children_by_type(self, node: Node, node_type: str) -> List[Node]:
        return [child for child in node.children if child.type == node_type]

    def _estimate_complexity(self, node: Node) -> int:
        """Estimate cyclomatic complexity by counting decision points."""
        complexity = 1  # Base complexity
        decision_types = {
            "if_statement", "elif_clause", "else_clause",
            "for_statement", "while_statement",
            "try_statement", "except_clause",
            "with_statement", "match_statement", "case_clause",
            "conditional_expression", "and", "or",
            "if_expression", "for_in_expression",
        }

        def count_decisions(n: Node) -> int:
            count = 1 if n.type in decision_types else 0
            for child in n.children:
                count += count_decisions(child)
            return count

        return complexity + count_decisions(node)

    def _build_local_symbol_map(self, symbols: List[SymbolInfo]) -> Dict[str, SymbolInfo]:
        """Build a map of symbol names to SymbolInfo for local resolution."""
        return {s.name: s for s in symbols}


class PythonExtractorV2(BaseLanguageExtractorV2):
    """Enhanced symbol extractor for Python code (V2)."""

    def extract_symbols(
        self, tree: Tree, file_path: str, content: str
    ) -> List[SymbolInfo]:
        symbols = []
        content_bytes = content.encode("utf-8")
        self._extract_from_node(
            tree.root_node, file_path, content_bytes, symbols, parent=None
        )
        return symbols

    def _extract_from_node(
        self,
        node: Node,
        file_path: str,
        content: bytes,
        symbols: List[SymbolInfo],
        parent: Optional[str],
    ) -> None:
        if node.type == "function_definition":
            symbol = self._extract_function(node, file_path, content, parent)
            if symbol:
                symbols.append(symbol)
                body = self._find_child_by_type(node, "block")
                if body:
                    for child in body.children:
                        self._extract_from_node(
                            child, file_path, content, symbols, symbol.symbol_id
                        )
            return

        if node.type == "class_definition":
            symbol = self._extract_class(node, file_path, content, parent)
            if symbol:
                symbols.append(symbol)
                body = self._find_child_by_type(node, "block")
                if body:
                    for child in body.children:
                        self._extract_from_node(
                            child, file_path, content, symbols, symbol.symbol_id
                        )
            return

        for child in node.children:
            self._extract_from_node(child, file_path, content, symbols, parent)

    def _extract_function(
        self, node: Node, file_path: str, content: bytes, parent: Optional[str]
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        kind = SymbolKind.METHOD if parent else SymbolKind.FUNCTION
        line = node.start_point[0] + 1  # 1-indexed

        # Determine visibility
        visibility = Visibility.PUBLIC
        if name.startswith("__") and not name.endswith("__"):
            visibility = Visibility.PRIVATE
        elif name.startswith("_"):
            visibility = Visibility.PROTECTED

        # Extract decorators
        decorators = self._extract_decorators(node, content)
        is_static = "@staticmethod" in decorators
        is_abstract = "@abstractmethod" in decorators

        # Check if async
        is_async = node.type == "async_function_definition" or any(
            child.type == "async" for child in node.children
        )

        # Extract parameters
        parameters = self._extract_parameters(node, content)

        # Extract return type
        return_type = self._extract_return_type(node, content)

        # Build signature
        signature = self._build_signature(name, parameters, return_type, is_async)

        # Extract docstring
        docstring = self._extract_docstring(node, content)

        # Estimate complexity
        complexity = self._estimate_complexity(node)

        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, kind, line),
            name=name,
            kind=kind,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=visibility,
            docstring=docstring,
            parent_symbol=parent,
            signature=signature,
            parameters=parameters,
            return_type=return_type,
            decorators=decorators,
            is_async=is_async,
            is_static=is_static,
            is_abstract=is_abstract,
            complexity=complexity,
        )

    def _extract_class(
        self, node: Node, file_path: str, content: bytes, parent: Optional[str]
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1  # 1-indexed
        visibility = Visibility.PRIVATE if name.startswith("_") else Visibility.PUBLIC

        # Extract decorators
        decorators = self._extract_decorators(node, content)
        is_abstract = "@abstractmethod" in decorators or "@ABC" in decorators

        # Extract base classes
        base_classes = self._extract_base_classes(node, content)

        docstring = self._extract_docstring(node, content)

        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.CLASS, line),
            name=name,
            kind=SymbolKind.CLASS,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=visibility,
            docstring=docstring,
            parent_symbol=parent,
            decorators=decorators,
            base_classes=base_classes,
            is_abstract=is_abstract,
        )

    def _extract_decorators(self, node: Node, content: bytes) -> List[str]:
        """Extract decorator names from a function or class."""
        decorators = []
        # Look for decorator nodes before the definition
        parent = node.parent
        if parent:
            for sibling in parent.children:
                if sibling.type == "decorator" and sibling.end_point[0] < node.start_point[0]:
                    decorator_text = self._get_node_text(sibling, content)
                    decorators.append(decorator_text.strip())
                elif sibling == node:
                    break
        return decorators

    def _extract_parameters(self, node: Node, content: bytes) -> List[ParameterInfo]:
        """Extract function parameters with type annotations."""
        parameters = []
        params_node = self._find_child_by_type(node, "parameters")
        if not params_node:
            return parameters

        for child in params_node.children:
            if child.type in ("identifier", "typed_parameter", "default_parameter",
                             "typed_default_parameter", "list_splat_pattern",
                             "dictionary_splat_pattern"):
                param = self._parse_parameter(child, content)
                if param:
                    parameters.append(param)
        return parameters

    def _parse_parameter(self, node: Node, content: bytes) -> Optional[ParameterInfo]:
        """Parse a single parameter node."""
        if node.type == "identifier":
            name = self._get_node_text(node, content)
            if name in ("self", "cls"):
                return None
            return ParameterInfo(name=name)

        elif node.type == "typed_parameter":
            name_node = self._find_child_by_type(node, "identifier")
            type_node = self._find_child_by_type(node, "type")
            name = self._get_node_text(name_node, content) if name_node else ""
            type_ann = self._get_node_text(type_node, content) if type_node else None
            if name in ("self", "cls"):
                return None
            return ParameterInfo(name=name, type_annotation=type_ann)

        elif node.type in ("default_parameter", "typed_default_parameter"):
            name_node = self._find_child_by_type(node, "identifier")
            name = self._get_node_text(name_node, content) if name_node else ""
            # Find default value
            for child in node.children:
                if child.type not in ("identifier", "type", ":"):
                    default = self._get_node_text(child, content)
                    return ParameterInfo(name=name, default_value=default)
            return ParameterInfo(name=name)

        elif node.type == "list_splat_pattern":
            name_node = self._find_child_by_type(node, "identifier")
            name = self._get_node_text(name_node, content) if name_node else "args"
            return ParameterInfo(name=f"*{name}", is_variadic=True)

        elif node.type == "dictionary_splat_pattern":
            name_node = self._find_child_by_type(node, "identifier")
            name = self._get_node_text(name_node, content) if name_node else "kwargs"
            return ParameterInfo(name=f"**{name}", is_keyword=True)

        return None

    def _extract_return_type(self, node: Node, content: bytes) -> Optional[str]:
        """Extract return type annotation."""
        for child in node.children:
            if child.type == "type":
                return self._get_node_text(child, content)
        return None

    def _build_signature(
        self,
        name: str,
        parameters: List[ParameterInfo],
        return_type: Optional[str],
        is_async: bool,
    ) -> str:
        """Build a human-readable function signature."""
        prefix = "async " if is_async else ""
        params_str = ", ".join(
            f"{p.name}: {p.type_annotation}" if p.type_annotation else p.name
            for p in parameters
        )
        sig = f"{prefix}def {name}({params_str})"
        if return_type:
            sig += f" -> {return_type}"
        return sig

    def _extract_base_classes(self, node: Node, content: bytes) -> List[str]:
        """Extract base class names from a class definition."""
        base_classes = []
        arg_list = self._find_child_by_type(node, "argument_list")
        if arg_list:
            for child in arg_list.children:
                if child.type == "identifier":
                    base_classes.append(self._get_node_text(child, content))
                elif child.type == "attribute":
                    base_classes.append(self._get_node_text(child, content))
        return base_classes

    def _extract_docstring(self, node: Node, content: bytes) -> Optional[str]:
        """Extract docstring from a function or class."""
        body = self._find_child_by_type(node, "block")
        if not body or not body.children:
            return None

        first_stmt = body.children[0]
        if first_stmt.type == "expression_statement":
            expr = first_stmt.children[0] if first_stmt.children else None
            if expr and expr.type == "string":
                docstring = self._get_node_text(expr, content)
                return docstring.strip('"""').strip("'''").strip()
        return None

    def extract_relationships(
        self, tree: Tree, symbols: List[SymbolInfo], content: str, file_path: str
    ) -> List[Relationship]:
        """Extract Python relationships with cross-file resolution metadata."""
        relationships = []
        content_bytes = content.encode("utf-8")
        local_symbols = self._build_local_symbol_map(symbols)

        # Extract imports with resolution metadata
        relationships.extend(self._extract_imports_with_resolution(tree.root_node, content_bytes, file_path))

        # Extract calls with resolution metadata
        relationships.extend(self._extract_calls_with_resolution(tree.root_node, symbols, content_bytes, local_symbols, file_path))

        # Extract inheritance with resolution metadata
        relationships.extend(self._extract_inheritance_with_resolution(tree.root_node, symbols, content_bytes, local_symbols, file_path))

        # Extract decorator relationships
        relationships.extend(self._extract_decorator_relationships(tree.root_node, symbols, content_bytes, local_symbols, file_path))

        return relationships


    def _extract_imports_with_resolution(
        self, node: Node, content: bytes, file_path: str
    ) -> List[Relationship]:
        """Extract imports with module path for cross-file resolution.

        Populates to_module_path and imported_names for later resolution.
        Sets is_resolved=False for all imports (resolved in Pass 2).
        """
        relationships = []

        # Handle 'import module' statements
        for import_node in self._find_nodes_by_type(node, "import_statement"):
            for name_node in self._find_nodes_by_type(import_node, "dotted_name"):
                module_name = self._get_node_text(name_node, content)
                line = import_node.start_point[0] + 1

                # Create file-level symbol ID for the from_symbol
                from_symbol_id = f"{file_path}:__file__:module:0"

                relationships.append(Relationship(
                    from_symbol="__file__",
                    to_symbol=module_name,
                    relationship_type=RelationshipType.IMPORTS,
                    line_number=line,
                    from_symbol_id=from_symbol_id,
                    to_symbol_id=None,  # Unresolved - will be resolved in Pass 2
                    to_module_path=module_name,
                    imported_names=[module_name.split(".")[-1]],  # The module itself
                    is_resolved=False,
                    is_external=False,  # Will be determined in Pass 2
                ))

        # Handle 'from module import name' statements
        for import_node in self._find_nodes_by_type(node, "import_from_statement"):
            module_node = self._find_child_by_type(import_node, "dotted_name")
            if not module_node:
                # Handle relative imports like 'from . import x'
                module_node = self._find_child_by_type(import_node, "relative_import")

            if module_node:
                module_name = self._get_node_text(module_node, content)
                line = import_node.start_point[0] + 1

                # Extract imported names
                imported_names = []
                for child in import_node.children:
                    if child.type == "dotted_name" and child != module_node:
                        imported_names.append(self._get_node_text(child, content))
                    elif child.type == "aliased_import":
                        name_node = self._find_child_by_type(child, "dotted_name")
                        if name_node:
                            imported_names.append(self._get_node_text(name_node, content))
                    elif child.type == "identifier":
                        imported_names.append(self._get_node_text(child, content))

                # Check for wildcard import
                if any(child.type == "wildcard_import" for child in import_node.children):
                    imported_names = ["*"]

                from_symbol_id = f"{file_path}:__file__:module:0"

                relationships.append(Relationship(
                    from_symbol="__file__",
                    to_symbol=module_name,
                    relationship_type=RelationshipType.IMPORTS,
                    line_number=line,
                    from_symbol_id=from_symbol_id,
                    to_symbol_id=None,  # Unresolved
                    to_module_path=module_name,
                    imported_names=imported_names,
                    is_resolved=False,
                    is_external=False,
                ))

        return relationships

    def _extract_calls_with_resolution(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract calls with cross-file awareness.

        - For local calls (target in same file): set is_resolved=True and to_symbol_id
        - For cross-file calls: set is_resolved=False and to_symbol_name
        """
        relationships = []
        {s.name for s in symbols}

        for func_node in self._find_nodes_by_type(node, "function_definition"):
            name_node = self._find_child_by_type(func_node, "identifier")
            if not name_node:
                continue
            caller_name = self._get_node_text(name_node, content)
            func_node.start_point[0] + 1

            # Find the caller symbol to get its symbol_id
            caller_symbol = local_symbols.get(caller_name)
            caller_symbol_id = caller_symbol.symbol_id if caller_symbol else None

            for call_node in self._find_nodes_by_type(func_node, "call"):
                func_expr = call_node.children[0] if call_node.children else None
                if not func_expr:
                    continue

                call_line = call_node.start_point[0] + 1

                if func_expr.type == "identifier":
                    callee_name = self._get_node_text(func_expr, content)

                    # Check if callee is a local symbol
                    if callee_name in local_symbols:
                        callee_symbol = local_symbols[callee_name]
                        relationships.append(Relationship(
                            from_symbol=caller_name,
                            to_symbol=callee_name,
                            relationship_type=RelationshipType.CALLS,
                            line_number=call_line,
                            from_symbol_id=caller_symbol_id,
                            to_symbol_id=callee_symbol.symbol_id,
                            to_symbol_name=callee_name,
                            is_resolved=True,  # Intra-file - resolved immediately
                            is_external=False,
                        ))
                    else:
                        # Cross-file or external call
                        relationships.append(Relationship(
                            from_symbol=caller_name,
                            to_symbol=callee_name,
                            relationship_type=RelationshipType.CALLS,
                            line_number=call_line,
                            from_symbol_id=caller_symbol_id,
                            to_symbol_id=None,  # Unresolved
                            to_symbol_name=callee_name,
                            is_resolved=False,  # Cross-file - deferred
                            is_external=False,  # Will be determined in Pass 2
                        ))

                elif func_expr.type == "attribute":
                    # Handle method calls like self.method() or obj.method()
                    attr_nodes = self._find_children_by_type(func_expr, "identifier")
                    if len(attr_nodes) >= 1:
                        # Get the method name (last identifier)
                        callee_name = self._get_node_text(attr_nodes[-1], content)

                        # Check if it's a local method
                        if callee_name in local_symbols:
                            callee_symbol = local_symbols[callee_name]
                            relationships.append(Relationship(
                                from_symbol=caller_name,
                                to_symbol=callee_name,
                                relationship_type=RelationshipType.CALLS,
                                line_number=call_line,
                                from_symbol_id=caller_symbol_id,
                                to_symbol_id=callee_symbol.symbol_id,
                                to_symbol_name=callee_name,
                                is_resolved=True,
                                is_external=False,
                            ))
                        else:
                            # Cross-file or external call
                            relationships.append(Relationship(
                                from_symbol=caller_name,
                                to_symbol=callee_name,
                                relationship_type=RelationshipType.CALLS,
                                line_number=call_line,
                                from_symbol_id=caller_symbol_id,
                                to_symbol_id=None,
                                to_symbol_name=callee_name,
                                is_resolved=False,
                                is_external=False,
                            ))

        return relationships

    def _extract_inheritance_with_resolution(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract inheritance with cross-file awareness.

        - For local base classes: set is_resolved=True and to_symbol_id
        - For cross-file base classes: set is_resolved=False and to_symbol_name
        """
        relationships = []

        for class_node in self._find_nodes_by_type(node, "class_definition"):
            name_node = self._find_child_by_type(class_node, "identifier")
            if not name_node:
                continue
            class_name = self._get_node_text(name_node, content)
            class_line = class_node.start_point[0] + 1

            # Find the class symbol to get its symbol_id
            class_symbol = local_symbols.get(class_name)
            class_symbol_id = class_symbol.symbol_id if class_symbol else None

            arg_list = self._find_child_by_type(class_node, "argument_list")
            if arg_list:
                for child in arg_list.children:
                    base_name = None
                    if child.type == "identifier":
                        base_name = self._get_node_text(child, content)
                    elif child.type == "attribute":
                        # Handle qualified names like module.ClassName
                        base_name = self._get_node_text(child, content)

                    if base_name:
                        # Check if base class is local
                        # For qualified names, check the last part
                        simple_name = base_name.split(".")[-1]

                        if simple_name in local_symbols:
                            base_symbol = local_symbols[simple_name]
                            relationships.append(Relationship(
                                from_symbol=class_name,
                                to_symbol=base_name,
                                relationship_type=RelationshipType.EXTENDS,
                                line_number=class_line,
                                from_symbol_id=class_symbol_id,
                                to_symbol_id=base_symbol.symbol_id,
                                to_symbol_name=base_name,
                                is_resolved=True,
                                is_external=False,
                            ))
                        else:
                            # Cross-file or external base class
                            relationships.append(Relationship(
                                from_symbol=class_name,
                                to_symbol=base_name,
                                relationship_type=RelationshipType.EXTENDS,
                                line_number=class_line,
                                from_symbol_id=class_symbol_id,
                                to_symbol_id=None,
                                to_symbol_name=base_name,
                                is_resolved=False,
                                is_external=False,
                            ))

        return relationships

    def _extract_decorator_relationships(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract DECORATES relationships with resolution metadata."""
        relationships = []

        for decorator_node in self._find_nodes_by_type(node, "decorator"):
            # Find what this decorator is applied to
            parent = decorator_node.parent
            if not parent:
                continue

            # Find the decorated function/class
            decorated_node = None
            for sibling in parent.children:
                if sibling.type in ("function_definition", "class_definition"):
                    if sibling.start_point[0] > decorator_node.end_point[0]:
                        decorated_node = sibling
                        break

            if decorated_node:
                name_node = self._find_child_by_type(decorated_node, "identifier")
                if name_node:
                    decorated_name = self._get_node_text(name_node, content)
                    decorator_text = self._get_node_text(decorator_node, content)
                    # Extract decorator name (without @)
                    decorator_name = decorator_text.lstrip("@").split("(")[0]

                    decorated_symbol = local_symbols.get(decorated_name)
                    decorator_symbol = local_symbols.get(decorator_name)

                    if decorator_symbol:
                        # Local decorator
                        relationships.append(Relationship(
                            from_symbol=decorator_name,
                            to_symbol=decorated_name,
                            relationship_type=RelationshipType.DECORATES,
                            line_number=decorator_node.start_point[0] + 1,
                            from_symbol_id=decorator_symbol.symbol_id,
                            to_symbol_id=decorated_symbol.symbol_id if decorated_symbol else None,
                            to_symbol_name=decorated_name,
                            is_resolved=True,
                            is_external=False,
                        ))
                    else:
                        # Cross-file or external decorator
                        relationships.append(Relationship(
                            from_symbol=decorator_name,
                            to_symbol=decorated_name,
                            relationship_type=RelationshipType.DECORATES,
                            line_number=decorator_node.start_point[0] + 1,
                            from_symbol_id=None,
                            to_symbol_id=decorated_symbol.symbol_id if decorated_symbol else None,
                            to_symbol_name=decorated_name,
                            is_resolved=False,
                            is_external=False,
                        ))

        return relationships



class JavaScriptExtractorV2(BaseLanguageExtractorV2):
    """Symbol extractor for JavaScript code (V2)."""

    def extract_symbols(
        self, tree: Tree, file_path: str, content: str
    ) -> List[SymbolInfo]:
        symbols = []
        content_bytes = content.encode("utf-8")
        self._extract_from_node(tree.root_node, file_path, content_bytes, symbols, None)
        return symbols

    def _extract_from_node(
        self,
        node: Node,
        file_path: str,
        content: bytes,
        symbols: List[SymbolInfo],
        parent: Optional[str],
    ) -> None:
        if node.type == "function_declaration":
            symbol = self._extract_function(node, file_path, content, parent)
            if symbol:
                symbols.append(symbol)
                body = self._find_child_by_type(node, "statement_block")
                if body:
                    for child in body.children:
                        self._extract_from_node(child, file_path, content, symbols, symbol.symbol_id)
            return

        if node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in self._find_nodes_by_type(node, "variable_declarator"):
                name_node = self._find_child_by_type(declarator, "identifier")
                value_node = self._find_child_by_type(declarator, "arrow_function")
                if name_node and value_node:
                    name = self._get_node_text(name_node, content)
                    line = node.start_point[0] + 1
                    symbols.append(SymbolInfo(
                        symbol_id=self._create_symbol_id(file_path, name, SymbolKind.FUNCTION, line),
                        name=name,
                        kind=SymbolKind.FUNCTION,
                        file_path=file_path,
                        start_line=line,
                        end_line=node.end_point[0] + 1,
                        visibility=Visibility.PUBLIC,
                        parent_symbol=parent,
                        is_async="async" in self._get_node_text(value_node, content)[:20],
                    ))

        if node.type == "class_declaration":
            symbol = self._extract_class(node, file_path, content, parent)
            if symbol:
                symbols.append(symbol)
                body = self._find_child_by_type(node, "class_body")
                if body:
                    for child in body.children:
                        self._extract_from_node(child, file_path, content, symbols, symbol.symbol_id)
            return

        if node.type == "method_definition":
            symbol = self._extract_method(node, file_path, content, parent)
            if symbol:
                symbols.append(symbol)
            return

        for child in node.children:
            self._extract_from_node(child, file_path, content, symbols, parent)

    def _extract_function(
        self, node: Node, file_path: str, content: bytes, parent: Optional[str]
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1
        is_async = any(child.type == "async" for child in node.children)

        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.FUNCTION, line),
            name=name,
            kind=SymbolKind.FUNCTION,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=Visibility.PUBLIC,
            parent_symbol=parent,
            is_async=is_async,
            complexity=self._estimate_complexity(node),
        )

    def _extract_class(
        self, node: Node, file_path: str, content: bytes, parent: Optional[str]
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1
        base_classes = []

        # Find extends clause
        heritage = self._find_child_by_type(node, "class_heritage")
        if heritage:
            for child in heritage.children:
                if child.type == "identifier":
                    base_classes.append(self._get_node_text(child, content))

        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.CLASS, line),
            name=name,
            kind=SymbolKind.CLASS,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=Visibility.PUBLIC,
            parent_symbol=parent,
            base_classes=base_classes,
        )

    def _extract_method(
        self, node: Node, file_path: str, content: bytes, parent: Optional[str]
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "property_identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1
        visibility = Visibility.PRIVATE if name.startswith("#") else Visibility.PUBLIC
        is_static = any(child.type == "static" for child in node.children)
        is_async = any(child.type == "async" for child in node.children)

        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.METHOD, line),
            name=name,
            kind=SymbolKind.METHOD,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=visibility,
            parent_symbol=parent,
            is_static=is_static,
            is_async=is_async,
            complexity=self._estimate_complexity(node),
        )

    def extract_relationships(
        self, tree: Tree, symbols: List[SymbolInfo], content: str, file_path: str
    ) -> List[Relationship]:
        """Extract JavaScript relationships with cross-file resolution metadata."""
        relationships = []
        content_bytes = content.encode("utf-8")
        local_symbols = self._build_local_symbol_map(symbols)

        relationships.extend(self._extract_imports_with_resolution(tree.root_node, content_bytes, file_path))
        relationships.extend(self._extract_calls_with_resolution(tree.root_node, symbols, content_bytes, local_symbols, file_path))
        relationships.extend(self._extract_inheritance_with_resolution(tree.root_node, symbols, content_bytes, local_symbols, file_path))

        return relationships

    def _extract_imports_with_resolution(
        self, node: Node, content: bytes, file_path: str
    ) -> List[Relationship]:
        """Extract JS/TS imports with module path for resolution."""
        relationships = []

        for import_node in self._find_nodes_by_type(node, "import_statement"):
            source = self._find_child_by_type(import_node, "string")
            if source:
                module_name = self._get_node_text(source, content).strip("'\"")
                line = import_node.start_point[0] + 1

                # Extract imported names
                imported_names = []
                import_clause = self._find_child_by_type(import_node, "import_clause")
                if import_clause:
                    # Default import
                    default_import = self._find_child_by_type(import_clause, "identifier")
                    if default_import:
                        imported_names.append(self._get_node_text(default_import, content))

                    # Named imports
                    named_imports = self._find_child_by_type(import_clause, "named_imports")
                    if named_imports:
                        for spec in self._find_nodes_by_type(named_imports, "import_specifier"):
                            name_node = self._find_child_by_type(spec, "identifier")
                            if name_node:
                                imported_names.append(self._get_node_text(name_node, content))

                    # Namespace import (import * as name)
                    namespace_import = self._find_child_by_type(import_clause, "namespace_import")
                    if namespace_import:
                        imported_names.append("*")

                from_symbol_id = f"{file_path}:__file__:module:0"

                # Determine if external (doesn't start with . or /)
                is_likely_external = not module_name.startswith(".") and not module_name.startswith("/")

                relationships.append(Relationship(
                    from_symbol="__file__",
                    to_symbol=module_name,
                    relationship_type=RelationshipType.IMPORTS,
                    line_number=line,
                    from_symbol_id=from_symbol_id,
                    to_symbol_id=None,
                    to_module_path=module_name,
                    imported_names=imported_names if imported_names else [module_name.split("/")[-1]],
                    is_resolved=False,
                    is_external=is_likely_external,  # Preliminary - confirmed in Pass 2
                ))

        return relationships

    def _extract_calls_with_resolution(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract JS calls with cross-file awareness."""
        relationships = []

        for func_node in self._find_nodes_by_type(node, "function_declaration"):
            name_node = self._find_child_by_type(func_node, "identifier")
            if not name_node:
                continue
            caller_name = self._get_node_text(name_node, content)
            caller_symbol = local_symbols.get(caller_name)
            caller_symbol_id = caller_symbol.symbol_id if caller_symbol else None

            for call_node in self._find_nodes_by_type(func_node, "call_expression"):
                func_expr = call_node.children[0] if call_node.children else None
                if func_expr and func_expr.type == "identifier":
                    callee_name = self._get_node_text(func_expr, content)
                    call_line = call_node.start_point[0] + 1

                    if callee_name in local_symbols:
                        callee_symbol = local_symbols[callee_name]
                        relationships.append(Relationship(
                            from_symbol=caller_name,
                            to_symbol=callee_name,
                            relationship_type=RelationshipType.CALLS,
                            line_number=call_line,
                            from_symbol_id=caller_symbol_id,
                            to_symbol_id=callee_symbol.symbol_id,
                            to_symbol_name=callee_name,
                            is_resolved=True,
                            is_external=False,
                        ))
                    else:
                        relationships.append(Relationship(
                            from_symbol=caller_name,
                            to_symbol=callee_name,
                            relationship_type=RelationshipType.CALLS,
                            line_number=call_line,
                            from_symbol_id=caller_symbol_id,
                            to_symbol_id=None,
                            to_symbol_name=callee_name,
                            is_resolved=False,
                            is_external=False,
                        ))

        return relationships

    def _extract_inheritance_with_resolution(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract JS inheritance with cross-file awareness."""
        relationships = []

        for class_node in self._find_nodes_by_type(node, "class_declaration"):
            name_node = self._find_child_by_type(class_node, "identifier")
            if not name_node:
                continue
            class_name = self._get_node_text(name_node, content)
            class_symbol = local_symbols.get(class_name)
            class_symbol_id = class_symbol.symbol_id if class_symbol else None

            heritage = self._find_child_by_type(class_node, "class_heritage")
            if heritage:
                for child in heritage.children:
                    if child.type == "identifier":
                        base_name = self._get_node_text(child, content)

                        if base_name in local_symbols:
                            base_symbol = local_symbols[base_name]
                            relationships.append(Relationship(
                                from_symbol=class_name,
                                to_symbol=base_name,
                                relationship_type=RelationshipType.EXTENDS,
                                line_number=class_node.start_point[0] + 1,
                                from_symbol_id=class_symbol_id,
                                to_symbol_id=base_symbol.symbol_id,
                                to_symbol_name=base_name,
                                is_resolved=True,
                                is_external=False,
                            ))
                        else:
                            relationships.append(Relationship(
                                from_symbol=class_name,
                                to_symbol=base_name,
                                relationship_type=RelationshipType.EXTENDS,
                                line_number=class_node.start_point[0] + 1,
                                from_symbol_id=class_symbol_id,
                                to_symbol_id=None,
                                to_symbol_name=base_name,
                                is_resolved=False,
                                is_external=False,
                            ))

        return relationships



class TypeScriptExtractorV2(JavaScriptExtractorV2):
    """Symbol extractor for TypeScript code with interface and type support (V2)."""

    def extract_symbols(
        self, tree: Tree, file_path: str, content: str
    ) -> List[SymbolInfo]:
        symbols = super().extract_symbols(tree, file_path, content)
        content_bytes = content.encode("utf-8")

        # Extract interfaces
        for interface_node in self._find_nodes_by_type(tree.root_node, "interface_declaration"):
            symbol = self._extract_interface(interface_node, file_path, content_bytes)
            if symbol:
                symbols.append(symbol)

        # Extract type aliases
        for type_node in self._find_nodes_by_type(tree.root_node, "type_alias_declaration"):
            symbol = self._extract_type_alias(type_node, file_path, content_bytes)
            if symbol:
                symbols.append(symbol)

        # Extract enums
        for enum_node in self._find_nodes_by_type(tree.root_node, "enum_declaration"):
            symbol = self._extract_enum(enum_node, file_path, content_bytes)
            if symbol:
                symbols.append(symbol)

        return symbols

    def _extract_interface(
        self, node: Node, file_path: str, content: bytes
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "type_identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1

        # Extract extended interfaces
        base_classes = []
        extends_clause = self._find_child_by_type(node, "extends_type_clause")
        if extends_clause:
            for child in extends_clause.children:
                if child.type == "type_identifier":
                    base_classes.append(self._get_node_text(child, content))

        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.INTERFACE, line),
            name=name,
            kind=SymbolKind.INTERFACE,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=Visibility.PUBLIC,
            base_classes=base_classes,
        )

    def _extract_type_alias(
        self, node: Node, file_path: str, content: bytes
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "type_identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1
        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.TYPE_ALIAS, line),
            name=name,
            kind=SymbolKind.TYPE_ALIAS,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=Visibility.PUBLIC,
        )

    def _extract_enum(
        self, node: Node, file_path: str, content: bytes
    ) -> Optional[SymbolInfo]:
        name_node = self._find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = self._get_node_text(name_node, content)
        line = node.start_point[0] + 1
        return SymbolInfo(
            symbol_id=self._create_symbol_id(file_path, name, SymbolKind.ENUM, line),
            name=name,
            kind=SymbolKind.ENUM,
            file_path=file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            visibility=Visibility.PUBLIC,
        )

    def extract_relationships(
        self, tree: Tree, symbols: List[SymbolInfo], content: str, file_path: str
    ) -> List[Relationship]:
        """Extract TypeScript relationships with cross-file resolution metadata."""
        relationships = super().extract_relationships(tree, symbols, content, file_path)
        content_bytes = content.encode("utf-8")
        local_symbols = self._build_local_symbol_map(symbols)

        # Extract implements relationships
        relationships.extend(
            self._extract_implements_with_resolution(tree.root_node, symbols, content_bytes, local_symbols, file_path)
        )

        # Extract interface extends
        relationships.extend(
            self._extract_interface_extends_with_resolution(tree.root_node, symbols, content_bytes, local_symbols, file_path)
        )

        return relationships

    def _extract_implements_with_resolution(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract IMPLEMENTS relationships with resolution metadata."""
        relationships = []

        for class_node in self._find_nodes_by_type(node, "class_declaration"):
            name_node = self._find_child_by_type(class_node, "identifier")
            if not name_node:
                continue
            class_name = self._get_node_text(name_node, content)
            class_symbol = local_symbols.get(class_name)
            class_symbol_id = class_symbol.symbol_id if class_symbol else None

            for child in class_node.children:
                if child.type == "implements_clause":
                    for type_node in child.children:
                        if type_node.type == "type_identifier":
                            interface_name = self._get_node_text(type_node, content)

                            if interface_name in local_symbols:
                                interface_symbol = local_symbols[interface_name]
                                relationships.append(Relationship(
                                    from_symbol=class_name,
                                    to_symbol=interface_name,
                                    relationship_type=RelationshipType.IMPLEMENTS,
                                    line_number=class_node.start_point[0] + 1,
                                    from_symbol_id=class_symbol_id,
                                    to_symbol_id=interface_symbol.symbol_id,
                                    to_symbol_name=interface_name,
                                    is_resolved=True,
                                    is_external=False,
                                ))
                            else:
                                relationships.append(Relationship(
                                    from_symbol=class_name,
                                    to_symbol=interface_name,
                                    relationship_type=RelationshipType.IMPLEMENTS,
                                    line_number=class_node.start_point[0] + 1,
                                    from_symbol_id=class_symbol_id,
                                    to_symbol_id=None,
                                    to_symbol_name=interface_name,
                                    is_resolved=False,
                                    is_external=False,
                                ))

        return relationships

    def _extract_interface_extends_with_resolution(
        self, node: Node, symbols: List[SymbolInfo], content: bytes,
        local_symbols: Dict[str, SymbolInfo], file_path: str
    ) -> List[Relationship]:
        """Extract interface EXTENDS relationships with resolution metadata."""
        relationships = []

        for interface_node in self._find_nodes_by_type(node, "interface_declaration"):
            name_node = self._find_child_by_type(interface_node, "type_identifier")
            if not name_node:
                continue
            interface_name = self._get_node_text(name_node, content)
            interface_symbol = local_symbols.get(interface_name)
            interface_symbol_id = interface_symbol.symbol_id if interface_symbol else None

            extends_clause = self._find_child_by_type(interface_node, "extends_type_clause")
            if extends_clause:
                for child in extends_clause.children:
                    if child.type == "type_identifier":
                        base_name = self._get_node_text(child, content)

                        if base_name in local_symbols:
                            base_symbol = local_symbols[base_name]
                            relationships.append(Relationship(
                                from_symbol=interface_name,
                                to_symbol=base_name,
                                relationship_type=RelationshipType.EXTENDS,
                                line_number=interface_node.start_point[0] + 1,
                                from_symbol_id=interface_symbol_id,
                                to_symbol_id=base_symbol.symbol_id,
                                to_symbol_name=base_name,
                                is_resolved=True,
                                is_external=False,
                            ))
                        else:
                            relationships.append(Relationship(
                                from_symbol=interface_name,
                                to_symbol=base_name,
                                relationship_type=RelationshipType.EXTENDS,
                                line_number=interface_node.start_point[0] + 1,
                                from_symbol_id=interface_symbol_id,
                                to_symbol_id=None,
                                to_symbol_name=base_name,
                                is_resolved=False,
                                is_external=False,
                            ))

        return relationships
