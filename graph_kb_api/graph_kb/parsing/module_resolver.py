"""Module resolver for converting import paths to file paths.

This module provides the ModuleResolver class that converts module import paths
to file paths based on language-specific resolution rules, enabling cross-file
relationship resolution during Pass 2 of the two-pass indexing architecture.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Set

from graph_kb_api.graph_kb.models.enums import Language


@dataclass
class ResolvedImport:
    """Result of resolving an import statement.

    Attributes:
        target_file: Resolved file path within the repository, or None if external.
        target_symbol_id: Symbol ID if a specific symbol was imported, or None.
        is_external: True if the import refers to an external package.
        module_path: Original module path from the import statement.
    """
    target_file: Optional[str]
    target_symbol_id: Optional[str]
    is_external: bool
    module_path: str


class ModuleResolver:
    """Resolves module paths to file paths and symbols.

    Supports Python and JavaScript/TypeScript module resolution with
    language-specific rules for finding the target file.
    """

    # JS/TS extensions to try in order
    JS_TS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx"]

    # JS/TS index file names to try in order
    JS_TS_INDEX_FILES = ["index.ts", "index.tsx", "index.js", "index.jsx"]

    def __init__(self, repo_path: str, file_set: Set[str]) -> None:
        """Initialize the module resolver.

        Args:
            repo_path: Absolute path to the repository root.
            file_set: Set of all file paths in the repository (relative to repo_path).
        """
        self.repo_path = Path(repo_path)
        self.file_set = file_set

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a path by resolving . and .. components.

        This is needed because PurePosixPath doesn't resolve .. components.

        Args:
            path: Path string to normalize.

        Returns:
            Normalized path with . and .. resolved.
        """
        parts = path.split("/")
        result = []

        for part in parts:
            if part == "." or part == "":
                continue
            elif part == "..":
                if result:
                    result.pop()
            else:
                result.append(part)

        return "/".join(result)

    def resolve_module_to_file(
        self,
        module_path: str,
        language: Language,
        source_file: Optional[str] = None,
    ) -> Optional[str]:
        """Convert module path to file path.

        Dispatches to language-specific resolution based on the language parameter.

        Args:
            module_path: Module import path (e.g., "utils.auth" or "./utils/auth").
            language: Programming language for resolution rules.
            source_file: Source file path for relative import resolution.

        Returns:
            Resolved file path relative to repo root, or None if not found/external.
        """
        if language == Language.PYTHON:
            return self._resolve_python_module(module_path, source_file)
        elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            return self._resolve_js_module(module_path, source_file)
        else:
            # Unsupported language
            return None

    def _resolve_python_module(
        self,
        module_path: str,
        source_file: Optional[str] = None,
    ) -> Optional[str]:
        """Python-specific module resolution.

        Resolution order:
        1. For relative imports (starting with .): resolve relative to source file
        2. For absolute imports: convert dots to path separators
        3. Check for direct file (e.g., utils/auth.py)
        4. Check for package init (e.g., utils/auth/__init__.py)

        Args:
            module_path: Python module path (e.g., "utils.auth" or ".auth").
            source_file: Source file path for relative import resolution.

        Returns:
            Resolved file path relative to repo root, or None if not found/external.
        """
        if not module_path:
            return None

        # Handle relative imports
        if module_path.startswith("."):
            return self._resolve_python_relative_import(module_path, source_file)

        # Convert dotted path to file path
        # e.g., "utils.auth" → "utils/auth"
        path_parts = module_path.split(".")
        base_path = "/".join(path_parts)

        # Try direct file first (Requirement 7.1)
        direct_file = f"{base_path}.py"
        if direct_file in self.file_set:
            return direct_file

        # Try package init file (Requirement 7.2)
        init_file = f"{base_path}/__init__.py"
        if init_file in self.file_set:
            return init_file

        # Not found - likely external (Requirement 7.4)
        return None

    def _resolve_python_relative_import(
        self,
        module_path: str,
        source_file: Optional[str],
    ) -> Optional[str]:
        """Resolve Python relative import.

        Args:
            module_path: Relative module path (e.g., ".auth" or "..utils.auth").
            source_file: Source file path for resolution base.

        Returns:
            Resolved file path, or None if not found.
        """
        if source_file is None:
            return None

        # Count leading dots to determine parent level
        dot_count = 0
        for char in module_path:
            if char == ".":
                dot_count += 1
            else:
                break

        # Get the module name after the dots
        remaining = module_path[dot_count:]

        # Get source directory
        source_path = PurePosixPath(source_file)
        source_dir = source_path.parent

        # Go up directories based on dot count
        # One dot means current package, two dots means parent package, etc.
        current_dir = source_dir
        for _ in range(dot_count - 1):
            current_dir = current_dir.parent

        # Build the target path
        if remaining:
            path_parts = remaining.split(".")
            target_base = str(current_dir / "/".join(path_parts))
        else:
            # Just dots, referring to the package itself
            target_base = str(current_dir)

        # Normalize path (remove any . or ..)
        target_base = str(PurePosixPath(target_base))

        # Try direct file first
        direct_file = f"{target_base}.py"
        if direct_file in self.file_set:
            return direct_file

        # Try package init file
        init_file = f"{target_base}/__init__.py"
        if init_file in self.file_set:
            return init_file

        return None

    def _resolve_js_module(
        self,
        module_path: str,
        source_file: Optional[str],
    ) -> Optional[str]:
        """JavaScript/TypeScript module resolution.

        Resolution order:
        1. For relative imports (starting with . or ..): resolve relative to source
        2. For bare imports: treat as external package
        3. Try extensions in order: .ts, .tsx, .js, .jsx
        4. Try index files: index.ts, index.tsx, index.js, index.jsx

        Args:
            module_path: JS/TS module path (e.g., "./utils/auth" or "lodash").
            source_file: Source file path for relative import resolution.

        Returns:
            Resolved file path relative to repo root, or None if not found/external.
        """
        if not module_path:
            return None

        # Check if it's a relative import (Requirement 8.3)
        if module_path.startswith("."):
            return self._resolve_js_relative_import(module_path, source_file)

        # Bare import - treat as external package (Requirement 8.4)
        return None

    def _resolve_js_relative_import(
        self,
        module_path: str,
        source_file: Optional[str],
    ) -> Optional[str]:
        """Resolve JavaScript/TypeScript relative import.

        Args:
            module_path: Relative module path (e.g., "./utils/auth" or "../config").
            source_file: Source file path for resolution base.

        Returns:
            Resolved file path, or None if not found.
        """
        if source_file is None:
            return None

        # Get source directory
        source_path = PurePosixPath(source_file)
        source_dir = source_path.parent

        # Resolve the relative path
        # Handle both "./" and "../" prefixes
        target_path = source_dir / module_path

        # Normalize the path (resolve . and ..) using manual resolution
        # PurePosixPath doesn't resolve .. components, so we do it manually
        target_base = self._normalize_path(str(target_path))

        # Try with extensions first (Requirement 8.1)
        for ext in self.JS_TS_EXTENSIONS:
            candidate = f"{target_base}{ext}"
            if candidate in self.file_set:
                return candidate

        # Try index files in directory (Requirement 8.2)
        for index_file in self.JS_TS_INDEX_FILES:
            candidate = f"{target_base}/{index_file}"
            if candidate in self.file_set:
                return candidate

        # Not found
        return None

    def resolve_import(
        self,
        module_path: str,
        language: Language,
        source_file: Optional[str] = None,
        imported_names: Optional[list] = None,
    ) -> ResolvedImport:
        """Resolve an import statement to a ResolvedImport result.

        This is a convenience method that wraps resolve_module_to_file and
        returns a structured result with external detection.

        Args:
            module_path: Module import path.
            language: Programming language.
            source_file: Source file for relative imports.
            imported_names: List of specific names imported (for future use).

        Returns:
            ResolvedImport with resolution result.
        """
        target_file = self.resolve_module_to_file(module_path, language, source_file)

        # Determine if external
        is_external = target_file is None

        # For bare JS/TS imports, they're definitely external
        if language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            if not module_path.startswith("."):
                is_external = True

        return ResolvedImport(
            target_file=target_file,
            target_symbol_id=None,  # Symbol resolution happens separately
            is_external=is_external,
            module_path=module_path,
        )
