"""Language detection and parsing for source code files.

This module handles detecting programming languages and parsing source files
into Abstract Syntax Trees (AST) using tree-sitter.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Tree

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.enums import Language as LangEnum

logger = EnhancedLogger(__name__)


@dataclass
class ParseResult:
    """Result of parsing a source file."""

    tree: Tree
    language: LangEnum
    success: bool
    error_message: Optional[str] = None


class LanguageParser(ABC):
    """Abstract base class for language detection and parsing.

    This interface defines the contract for detecting programming languages
    and parsing source files into Abstract Syntax Trees.
    """

    @abstractmethod
    def detect_language(self, file_path: str, content: Optional[str] = None) -> LangEnum:
        """Detect the programming language of a file.

        Args:
            file_path: Path to the file.
            content: Optional file content for heuristic detection.

        Returns:
            Detected language enum value.
        """
        pass

    @abstractmethod
    def supports_language(self, language: LangEnum) -> bool:
        """Check if AST parsing is supported for a language.

        Args:
            language: Language to check.

        Returns:
            True if tree-sitter parsing is available.
        """
        pass

    @abstractmethod
    def parse(self, content: str, language: LangEnum) -> Optional[ParseResult]:
        """Parse source code into an AST.

        Args:
            content: Source code content.
            language: Programming language of the content.

        Returns:
            ParseResult with the AST tree, or None if parsing fails.
        """
        pass

    @abstractmethod
    def parse_file(self, file_path: str, content: Optional[str] = None) -> Optional[ParseResult]:
        """Parse a file into an AST.

        Args:
            file_path: Path to the file.
            content: Optional file content (will be read if not provided).

        Returns:
            ParseResult with the AST tree, or None if parsing fails.
        """
        pass


class TreeSitterLanguageParser(LanguageParser):
    """Detects programming languages and parses source files.

    This class provides functionality to:
    - Detect programming language from file extension
    - Parse source files into AST using tree-sitter
    - Handle fallback for unsupported languages
    """

    # Extension to language mapping
    EXTENSION_MAP: Dict[str, LangEnum] = {
        ".py": LangEnum.PYTHON,
        ".ts": LangEnum.TYPESCRIPT,
        ".tsx": LangEnum.TYPESCRIPT,
        ".js": LangEnum.JAVASCRIPT,
        ".jsx": LangEnum.JAVASCRIPT,
        ".go": LangEnum.GO,
        ".java": LangEnum.JAVA,
        ".rb": LangEnum.RUBY,
        ".rs": LangEnum.RUST,
        ".c": LangEnum.C,
        ".cpp": LangEnum.CPP,
        ".cc": LangEnum.CPP,
        ".cxx": LangEnum.CPP,
        ".cs": LangEnum.CSHARP,
        ".md": LangEnum.MARKDOWN,
        ".yaml": LangEnum.YAML,
        ".yml": LangEnum.YAML,
        ".json": LangEnum.JSON,
    }
    """Detects programming languages and parses source files.

    This class provides functionality to:
    - Detect programming language from file extension
    - Parse source files into AST using tree-sitter
    - Handle fallback for unsupported languages
    """

    # Extension to language mapping
    EXTENSION_MAP: Dict[str, LangEnum] = {
        ".py": LangEnum.PYTHON,
        ".ts": LangEnum.TYPESCRIPT,
        ".tsx": LangEnum.TYPESCRIPT,
        ".js": LangEnum.JAVASCRIPT,
        ".jsx": LangEnum.JAVASCRIPT,
        ".go": LangEnum.GO,
        ".java": LangEnum.JAVA,
        ".rb": LangEnum.RUBY,
        ".rs": LangEnum.RUST,
        ".c": LangEnum.C,
        ".cpp": LangEnum.CPP,
        ".cc": LangEnum.CPP,
        ".cxx": LangEnum.CPP,
        ".cs": LangEnum.CSHARP,
        ".md": LangEnum.MARKDOWN,
        ".yaml": LangEnum.YAML,
        ".yml": LangEnum.YAML,
        ".json": LangEnum.JSON,
    }

    def __init__(self):
        """Initialize the LanguageParser with tree-sitter parsers."""
        self._parsers: Dict[LangEnum, Parser] = {}
        self._languages: Dict[LangEnum, Language] = {}
        self._initialize_parsers()

    def _initialize_parsers(self) -> None:
        """Initialize tree-sitter parsers for supported languages."""
        # Python parser
        try:
            py_lang = Language(tree_sitter_python.language())
            py_parser = Parser(py_lang)
            self._languages[LangEnum.PYTHON] = py_lang
            self._parsers[LangEnum.PYTHON] = py_parser
            logger.debug("Initialized Python parser")
        except Exception as e:
            logger.warning(f"Failed to initialize Python parser: {e}")

        # JavaScript parser
        try:
            js_lang = Language(tree_sitter_javascript.language())
            js_parser = Parser(js_lang)
            self._languages[LangEnum.JAVASCRIPT] = js_lang
            self._parsers[LangEnum.JAVASCRIPT] = js_parser
            logger.debug("Initialized JavaScript parser")
        except Exception as e:
            logger.warning(f"Failed to initialize JavaScript parser: {e}")

        # TypeScript parser
        try:
            ts_lang = Language(tree_sitter_typescript.language_typescript())
            ts_parser = Parser(ts_lang)
            self._languages[LangEnum.TYPESCRIPT] = ts_lang
            self._parsers[LangEnum.TYPESCRIPT] = ts_parser
            logger.debug("Initialized TypeScript parser")
        except Exception as e:
            logger.warning(f"Failed to initialize TypeScript parser: {e}")

    def detect_language(self, file_path: str, content: Optional[str] = None) -> LangEnum:
        """Detect the programming language of a file.

        Args:
            file_path: Path to the file.
            content: Optional file content for heuristic detection.

        Returns:
            Detected language enum value.
        """
        ext = Path(file_path).suffix.lower()
        language = self.EXTENSION_MAP.get(ext, LangEnum.UNKNOWN)

        # Additional heuristics for ambiguous cases
        if language == LangEnum.UNKNOWN and content:
            # Check for shebang
            if content.startswith("#!/"):
                first_line = content.split("\n")[0].lower()
                if "python" in first_line:
                    return LangEnum.PYTHON
                elif "node" in first_line or "deno" in first_line:
                    return LangEnum.JAVASCRIPT

        return language

    def supports_language(self, language: LangEnum) -> bool:
        """Check if AST parsing is supported for a language.

        Args:
            language: Language to check.

        Returns:
            True if tree-sitter parsing is available.
        """
        return language in self._parsers

    def get_supported_languages(self) -> list:
        """Get list of languages with AST parsing support.

        Returns:
            List of supported language enum values.
        """
        return list(self._parsers.keys())

    def parse(self, content: str, language: LangEnum) -> Optional[ParseResult]:
        """Parse source code into an AST.

        Args:
            content: Source code content.
            language: Programming language of the content.

        Returns:
            ParseResult with the AST tree, or None if parsing fails.
        """
        if not self.supports_language(language):
            logger.debug(f"No parser available for {language.value}")
            return None

        parser = self._parsers[language]

        try:
            # Parse the content
            tree = parser.parse(content.encode("utf-8"))

            # Check for parse errors
            has_errors = tree.root_node.has_error

            if has_errors:
                logger.warning(f"Parse errors detected in {language.value} code")
                return ParseResult(
                    tree=tree,
                    language=language,
                    success=True,  # Still return the tree, it may be partially valid
                    error_message="Parse errors detected in source code",
                )

            return ParseResult(
                tree=tree,
                language=language,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to parse {language.value} code: {e}")
            return ParseResult(
                tree=None,
                language=language,
                success=False,
                error_message=str(e),
            )

    def parse_file(self, file_path: str, content: Optional[str] = None) -> Optional[ParseResult]:
        """Parse a file into an AST.

        Args:
            file_path: Path to the file.
            content: Optional file content (will be read if not provided).

        Returns:
            ParseResult with the AST tree, or None if parsing fails.
        """
        # Read content if not provided
        if content is None:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.error(f"Failed to read file {file_path}: {e}")
                return None

        # Detect language
        language = self.detect_language(file_path, content)

        if language == LangEnum.UNKNOWN:
            logger.debug(f"Unknown language for file {file_path}")
            return None

        # Parse if supported
        if self.supports_language(language):
            return self.parse(content, language)

        # Return None for unsupported languages (fallback to text-based processing)
        logger.debug(f"No AST parser for {language.value}, will use text-based processing")
        return None

    def get_node_text(self, node: Node, content: bytes) -> str:
        """Extract text content from an AST node.

        Args:
            node: Tree-sitter node.
            content: Original source content as bytes.

        Returns:
            Text content of the node.
        """
        return content[node.start_byte:node.end_byte].decode("utf-8")

    def walk_tree(self, tree: Tree):
        """Generator to walk all nodes in a tree.

        Args:
            tree: Tree-sitter tree.

        Yields:
            Each node in the tree in depth-first order.
        """
        cursor = tree.walk()

        visited_children = False
        while True:
            if not visited_children:
                yield cursor.node
                if not cursor.goto_first_child():
                    visited_children = True
            elif cursor.goto_next_sibling():
                visited_children = False
            elif not cursor.goto_parent():
                break
