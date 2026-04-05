"""Code chunking for the knowledge base.

This module handles splitting source code and documentation into
semantically coherent chunks suitable for embedding and retrieval.
"""

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import List, Optional, Tuple

import tiktoken
from tree_sitter import Tree

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.base import Chunk, SymbolInfo
from ..models.enums import Language

logger = EnhancedLogger(__name__)


def get_default_max_tokens() -> int:
    """Get the default max tokens from embedding model configuration.

    Returns the max_tokens for the configured embedding model, falling back
    to a safe default if settings cannot be loaded.
    """
    try:
        from graph_kb_api.config import settings
        return settings.embedding_max_tokens
    except Exception:
        # Fallback if settings not available (e.g., during testing)
        return int(8191 / 2) # reduce max tokens to prevent OOM


class Chunker(ABC):
    """Abstract base class for content chunking.

    This interface defines the contract for splitting code and text into
    semantically coherent chunks suitable for embedding and retrieval.
    """

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Args:
            text: Text to count tokens for.

        Returns:
            Number of tokens.
        """
        pass

    @abstractmethod
    def chunk_code(
        self,
        content: str,
        tree: Tree,
        symbols: List[SymbolInfo],
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk a code file based on syntax tree structure.

        Args:
            content: Source code content.
            tree: Tree-sitter syntax tree.
            symbols: Extracted symbols from the file.
            repo_id: Repository identifier.
            file_path: Path to the source file.
            language: Programming language.
            commit_sha: Current commit SHA.

        Returns:
            List of Chunk objects.
        """
        pass

    @abstractmethod
    def chunk_text(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk a non-code file by paragraph/heading boundaries.

        Args:
            content: File content.
            repo_id: Repository identifier.
            file_path: Path to the file.
            commit_sha: Current commit SHA.

        Returns:
            List of Chunk objects.
        """
        pass

    @abstractmethod
    def ensure_chunk_fits(self, chunk: Chunk) -> List[Chunk]:
        """Ensure a chunk fits within max_tokens, splitting if necessary.

        Args:
            chunk: The chunk to validate/split.

        Returns:
            List containing either the original chunk (if it fits) or
            multiple smaller chunks that each fit within max_tokens.
        """
        pass


class SemanticChunker(Chunker):
    """Splits code and text into semantically coherent chunks.

    This class provides functionality to:
    - Chunk code files based on syntax tree structure (one chunk per function/method)
    - Chunk non-code files by paragraph/heading boundaries
    - Split oversized chunks at logical boundaries
    - Track token counts for embedding limits
    - Guarantee all chunks are under the configured token limit
    """
    """Splits code and text into semantically coherent chunks.

    This class provides functionality to:
    - Chunk code files based on syntax tree structure (one chunk per function/method)
    - Chunk non-code files by paragraph/heading boundaries
    - Split oversized chunks at logical boundaries
    - Track token counts for embedding limits
    - Guarantee all chunks are under the configured token limit
    """


    def __init__(self, max_tokens: Optional[int] = None):
        """Initialize the Chunker.

        Args:
            max_tokens: Maximum tokens per chunk. If None, uses the embedding
                       model's max_tokens from settings (recommended).
        """
        if max_tokens is None:
            self.max_tokens = get_default_max_tokens()
            logger.info(f"Chunker initialized with max_tokens={self.max_tokens} from embedding model config")
        else:
            self.max_tokens = max_tokens
            logger.info(f"Chunker initialized with explicit max_tokens={self.max_tokens}")
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Args:
            text: Text to count tokens for.

        Returns:
            Number of tokens.
        """
        return len(self._tokenizer.encode(text))

    def chunk_code(
        self,
        content: str,
        tree: Tree,
        symbols: List[SymbolInfo],
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk a code file based on syntax tree structure.

        Creates one chunk per function/method by default.
        Oversized functions are split at control-flow boundaries.

        Args:
            content: Source code content.
            tree: Tree-sitter syntax tree.
            symbols: Extracted symbols from the file.
            repo_id: Repository identifier.
            file_path: Path to the source file.
            language: Programming language.
            commit_sha: Current commit SHA.

        Returns:
            List of Chunk objects.
        """
        chunks = []
        content_lines = content.split("\n")

        # Get top-level functions and methods
        function_symbols = [
            s for s in symbols
            if s.kind.value in ("function", "method")
            and s.parent_symbol is None or s.kind.value == "method"
        ]

        # Track which lines are covered by function chunks
        covered_lines = set()

        for symbol in function_symbols:
            # Extract function content
            start_line = symbol.start_line - 1  # Convert to 0-indexed
            end_line = symbol.end_line
            func_lines = content_lines[start_line:end_line]
            func_content = "\n".join(func_lines)

            # Check token count
            token_count = self.count_tokens(func_content)

            if token_count <= self.max_tokens:
                # Create single chunk for this function
                chunk = self._create_chunk(
                    content=func_content,
                    repo_id=repo_id,
                    file_path=file_path,
                    language=language,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    symbols_defined=[symbol.name],
                    symbols_referenced=self._extract_references(func_content, symbols),
                    commit_sha=commit_sha,
                )
                chunks.append(chunk)
            else:
                # Split large function
                sub_chunks = self._split_large_function(
                    func_content,
                    symbol,
                    repo_id,
                    file_path,
                    language,
                    commit_sha,
                    symbols,
                )
                chunks.extend(sub_chunks)

            # Mark lines as covered
            for line in range(start_line, end_line):
                covered_lines.add(line)

        # Handle class-level code and module-level code not in functions
        uncovered_ranges = self._find_uncovered_ranges(
            len(content_lines), covered_lines
        )

        for start, end in uncovered_ranges:
            range_content = "\n".join(content_lines[start:end])
            if range_content.strip():
                token_count = self.count_tokens(range_content)
                if token_count > 0:
                    if token_count <= self.max_tokens:
                        chunk = self._create_chunk(
                            content=range_content,
                            repo_id=repo_id,
                            file_path=file_path,
                            language=language,
                            start_line=start + 1,
                            end_line=end,
                            symbols_defined=[],
                            symbols_referenced=self._extract_references(range_content, symbols),
                            commit_sha=commit_sha,
                        )
                        chunks.append(chunk)
                    else:
                        # Split oversized uncovered range by lines
                        logger.info(
                            f"Uncovered range {start+1}-{end} exceeds max_tokens "
                            f"({token_count} > {self.max_tokens}), splitting by lines"
                        )
                        sub_chunks = self._split_by_lines(
                            range_content, repo_id, file_path, language, commit_sha
                        )
                        # Adjust line numbers for sub_chunks
                        for sub_chunk in sub_chunks:
                            sub_chunk.start_line += start
                            sub_chunk.end_line += start
                            sub_chunk.symbols_referenced = self._extract_references(
                                sub_chunk.content, symbols
                            )
                        chunks.extend(sub_chunks)

        return sorted(chunks, key=lambda c: c.start_line)

    def chunk_text(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk a non-code file by paragraph/heading boundaries.

        Args:
            content: File content.
            repo_id: Repository identifier.
            file_path: Path to the file.
            commit_sha: Current commit SHA.

        Returns:
            List of Chunk objects.
        """
        chunks = []
        language = self._detect_text_language(file_path)

        if language == Language.MARKDOWN:
            chunks = self._chunk_markdown(content, repo_id, file_path, commit_sha)
        elif language == Language.YAML:
            chunks = self._chunk_yaml(content, repo_id, file_path, commit_sha)
        elif language == Language.JSON:
            # JSON is typically one chunk unless very large
            chunks = self._chunk_json(content, repo_id, file_path, commit_sha)
        else:
            # Generic text chunking by paragraphs
            chunks = self._chunk_paragraphs(content, repo_id, file_path, language, commit_sha)

        return chunks

    def _chunk_markdown(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk markdown by headings."""
        chunks = []
        lines = content.split("\n")

        # Find heading positions
        heading_pattern = re.compile(r"^#{1,6}\s+")
        sections = []
        current_start = 0

        for i, line in enumerate(lines):
            if heading_pattern.match(line) and i > 0:
                sections.append((current_start, i))
                current_start = i

        # Add final section
        sections.append((current_start, len(lines)))

        for start, end in sections:
            section_content = "\n".join(lines[start:end])
            if section_content.strip():
                token_count = self.count_tokens(section_content)

                if token_count <= self.max_tokens:
                    chunk = self._create_chunk(
                        content=section_content,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=Language.MARKDOWN,
                        start_line=start + 1,
                        end_line=end,
                        symbols_defined=[],
                        symbols_referenced=[],
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)
                else:
                    # Split large section by paragraphs
                    sub_chunks = self._split_by_paragraphs(
                        section_content, start, repo_id, file_path,
                        Language.MARKDOWN, commit_sha
                    )
                    chunks.extend(sub_chunks)

        return chunks

    def _chunk_yaml(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk YAML by top-level keys."""
        chunks = []
        lines = content.split("\n")

        # Find top-level key positions (lines starting without indentation)
        key_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:")
        sections = []
        current_start = 0

        for i, line in enumerate(lines):
            if key_pattern.match(line) and i > 0:
                sections.append((current_start, i))
                current_start = i

        sections.append((current_start, len(lines)))

        for start, end in sections:
            section_content = "\n".join(lines[start:end])
            if section_content.strip():
                chunk = self._create_chunk(
                    content=section_content,
                    repo_id=repo_id,
                    file_path=file_path,
                    language=Language.YAML,
                    start_line=start + 1,
                    end_line=end,
                    symbols_defined=[],
                    symbols_referenced=[],
                    commit_sha=commit_sha,
                )
                chunks.append(chunk)

        return chunks

    def _chunk_json(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk JSON file."""
        token_count = self.count_tokens(content)
        lines = content.split("\n")

        if token_count <= self.max_tokens:
            return [self._create_chunk(
                content=content,
                repo_id=repo_id,
                file_path=file_path,
                language=Language.JSON,
                start_line=1,
                end_line=len(lines),
                symbols_defined=[],
                symbols_referenced=[],
                commit_sha=commit_sha,
            )]

        # For large JSON, split by lines (not ideal but safe)
        return self._split_by_lines(
            content, repo_id, file_path, Language.JSON, commit_sha
        )

    def _chunk_paragraphs(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
    ) -> List[Chunk]:
        """Chunk text by paragraphs."""
        chunks = []
        paragraphs = content.split("\n\n")
        current_line = 1

        for para in paragraphs:
            if para.strip():
                para_lines = para.count("\n") + 1
                chunk = self._create_chunk(
                    content=para,
                    repo_id=repo_id,
                    file_path=file_path,
                    language=language,
                    start_line=current_line,
                    end_line=current_line + para_lines - 1,
                    symbols_defined=[],
                    symbols_referenced=[],
                    commit_sha=commit_sha,
                )
                chunks.append(chunk)
            current_line += para.count("\n") + 2  # +2 for the blank line

        return chunks

    def _split_large_function(
        self,
        content: str,
        symbol: SymbolInfo,
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
        all_symbols: List[SymbolInfo],
    ) -> List[Chunk]:
        """Split a large function at control-flow boundaries.

        Args:
            content: Function content.
            symbol: Symbol info for the function.
            repo_id: Repository identifier.
            file_path: Path to the source file.
            language: Programming language.
            commit_sha: Current commit SHA.
            all_symbols: All symbols for reference extraction.

        Returns:
            List of sub-chunks.
        """
        chunks = []
        lines = content.split("\n")

        # Use 95% of max_tokens as safety margin
        safe_max_tokens = int(self.max_tokens * 0.95)

        # Find control-flow boundaries (if, for, while, try, etc.)
        control_flow_patterns = [
            r"^\s*(if|elif|else|for|while|try|except|finally|with|match|case)\b",
            r"^\s*(def|class|async def)\b",
        ]
        combined_pattern = re.compile("|".join(control_flow_patterns))

        # Find split points
        split_points = [0]
        for i, line in enumerate(lines):
            if combined_pattern.match(line) and i > 0:
                split_points.append(i)
        split_points.append(len(lines))

        # If no control-flow boundaries found, fall back to line-based splitting
        if len(split_points) <= 2:
            return self._split_function_by_lines(
                content, symbol, repo_id, file_path, language, commit_sha, all_symbols
            )

        # Create chunks from split points
        current_chunk_lines = []
        current_start = 0

        for i in range(len(split_points) - 1):
            start = split_points[i]
            end = split_points[i + 1]
            segment = lines[start:end]

            # Check actual token count of combined content
            test_chunk = current_chunk_lines + segment
            test_content = "\n".join(test_chunk)
            actual_tokens = self.count_tokens(test_content)

            if actual_tokens <= safe_max_tokens:
                current_chunk_lines.extend(segment)
            else:
                # Save current chunk if not empty
                if current_chunk_lines:
                    chunk_content = "\n".join(current_chunk_lines)
                    chunk = self._create_chunk(
                        content=chunk_content,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        start_line=symbol.start_line + current_start,
                        end_line=symbol.start_line + current_start + len(current_chunk_lines) - 1,
                        symbols_defined=[symbol.name] if current_start == 0 else [],
                        symbols_referenced=self._extract_references(chunk_content, all_symbols),
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)

                # Start new chunk
                current_start = start
                current_chunk_lines = segment

        # Save final chunk
        if current_chunk_lines:
            chunk_content = "\n".join(current_chunk_lines)
            chunk = self._create_chunk(
                content=chunk_content,
                repo_id=repo_id,
                file_path=file_path,
                language=language,
                start_line=symbol.start_line + current_start,
                end_line=symbol.start_line + current_start + len(current_chunk_lines) - 1,
                symbols_defined=[symbol.name] if current_start == 0 else [],
                symbols_referenced=self._extract_references(chunk_content, all_symbols),
                commit_sha=commit_sha,
            )
            chunks.append(chunk)

        return chunks

    def _split_function_by_lines(
        self,
        content: str,
        symbol: SymbolInfo,
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
        all_symbols: List[SymbolInfo],
    ) -> List[Chunk]:
        """Split a function by lines when no control-flow boundaries exist.

        Handles oversized single lines by using token-aware splitting.
        Uses actual token counting on joined content to avoid drift.
        """
        chunks = []
        lines = content.split("\n")

        # Use 95% of max_tokens as safety margin
        safe_max_tokens = int(self.max_tokens * 0.95)

        current_chunk_lines = []
        current_start = 0

        for i, line in enumerate(lines):
            line_tokens = self.count_tokens(line)

            # Handle oversized single lines
            if line_tokens > self.max_tokens:
                # Save current chunk if not empty
                if current_chunk_lines:
                    chunk_content = "\n".join(current_chunk_lines)
                    chunk = self._create_chunk(
                        content=chunk_content,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        start_line=symbol.start_line + current_start,
                        end_line=symbol.start_line + current_start + len(current_chunk_lines) - 1,
                        symbols_defined=[symbol.name] if current_start == 0 else [],
                        symbols_referenced=self._extract_references(chunk_content, all_symbols),
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)

                # Split the oversized line
                logger.warning(
                    f"Line {i+1} in function {symbol.name} exceeds max_tokens "
                    f"({line_tokens} > {self.max_tokens}), splitting by tokens"
                )
                line_parts = self._split_text_by_tokens(line)
                for part in line_parts:
                    chunk = self._create_chunk(
                        content=part,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        start_line=symbol.start_line + i,
                        end_line=symbol.start_line + i,
                        symbols_defined=[],
                        symbols_referenced=self._extract_references(part, all_symbols),
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)

                # Reset for next line
                current_start = i + 1
                current_chunk_lines = []
            else:
                # Check actual token count of joined content (accounts for newlines)
                test_chunk = current_chunk_lines + [line]
                test_content = "\n".join(test_chunk)
                actual_tokens = self.count_tokens(test_content)

                if actual_tokens <= safe_max_tokens:
                    current_chunk_lines.append(line)
                else:
                    # Save current chunk if not empty
                    if current_chunk_lines:
                        chunk_content = "\n".join(current_chunk_lines)
                        chunk = self._create_chunk(
                            content=chunk_content,
                            repo_id=repo_id,
                            file_path=file_path,
                            language=language,
                            start_line=symbol.start_line + current_start,
                            end_line=symbol.start_line + current_start + len(current_chunk_lines) - 1,
                            symbols_defined=[symbol.name] if current_start == 0 else [],
                            symbols_referenced=self._extract_references(chunk_content, all_symbols),
                            commit_sha=commit_sha,
                        )
                        chunks.append(chunk)

                    # Start new chunk
                    current_start = i
                    current_chunk_lines = [line]

        # Save final chunk
        if current_chunk_lines:
            chunk_content = "\n".join(current_chunk_lines)
            chunk = self._create_chunk(
                content=chunk_content,
                repo_id=repo_id,
                file_path=file_path,
                language=language,
                start_line=symbol.start_line + current_start,
                end_line=symbol.start_line + current_start + len(current_chunk_lines) - 1,
                symbols_defined=[symbol.name] if current_start == 0 else [],
                symbols_referenced=self._extract_references(chunk_content, all_symbols),
                commit_sha=commit_sha,
            )
            chunks.append(chunk)

        return chunks

    def _split_by_paragraphs(
        self,
        content: str,
        base_line: int,
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
    ) -> List[Chunk]:
        """Split content by paragraphs."""
        chunks = []
        paragraphs = content.split("\n\n")
        current_line = base_line

        current_chunk = []
        current_tokens = 0
        chunk_start = current_line

        for para in paragraphs:
            para_tokens = self.count_tokens(para)
            para_lines = para.count("\n") + 1

            if current_tokens + para_tokens <= self.max_tokens:
                current_chunk.append(para)
                current_tokens += para_tokens
            else:
                # Save current chunk
                if current_chunk:
                    chunk_content = "\n\n".join(current_chunk)
                    chunk = self._create_chunk(
                        content=chunk_content,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        start_line=chunk_start + 1,
                        end_line=current_line,
                        symbols_defined=[],
                        symbols_referenced=[],
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)

                # Start new chunk
                current_chunk = [para]
                current_tokens = para_tokens
                chunk_start = current_line

            current_line += para_lines + 1  # +1 for blank line

        # Save final chunk
        if current_chunk:
            chunk_content = "\n\n".join(current_chunk)
            chunk = self._create_chunk(
                content=chunk_content,
                repo_id=repo_id,
                file_path=file_path,
                language=language,
                start_line=chunk_start + 1,
                end_line=current_line,
                symbols_defined=[],
                symbols_referenced=[],
                commit_sha=commit_sha,
            )
            chunks.append(chunk)

        return chunks

    def _split_by_lines(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        language: Language,
        commit_sha: str,
    ) -> List[Chunk]:
        """Split content by lines when other methods fail.

        Guarantees all returned chunks are under max_tokens by:
        1. Splitting by lines when possible
        2. Using token-aware character splitting for oversized lines

        Note: Uses actual token counting on joined content to avoid drift
        from newline tokens not being counted individually.
        """
        chunks = []
        lines = content.split("\n")

        # Use 95% of max_tokens as safety margin (same as _split_text_by_tokens)
        safe_max_tokens = int(self.max_tokens * 0.95)

        logger.debug(
            f"_split_by_lines: {len(lines)} lines, max_tokens={self.max_tokens}, "
            f"safe_max={safe_max_tokens}, total_tokens={self.count_tokens(content)}"
        )

        current_chunk = []
        chunk_start = 0

        for i, line in enumerate(lines):
            line_tokens = self.count_tokens(line)

            # If a single line exceeds max_tokens, we need to split the line itself
            if line_tokens > self.max_tokens:
                logger.warning(
                    f"Line {i+1} exceeds max_tokens ({line_tokens} > {self.max_tokens}). "
                    f"Splitting line using token-aware chunking."
                )
                # Save current chunk if it has content
                if current_chunk:
                    chunk = self._create_chunk(
                        content="\n".join(current_chunk),
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        start_line=chunk_start + 1,
                        end_line=i,
                        symbols_defined=[],
                        symbols_referenced=[],
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)

                # Split the oversized line using token-aware splitting
                line_chunks = self._split_text_by_tokens(line)
                for line_chunk in line_chunks:
                    chunk = self._create_chunk(
                        content=line_chunk,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        start_line=i + 1,
                        end_line=i + 1,
                        symbols_defined=[],
                        symbols_referenced=[],
                        commit_sha=commit_sha,
                    )
                    chunks.append(chunk)

                # Reset for next line
                current_chunk = []
                chunk_start = i + 1
            else:
                # Check actual token count of joined content (accounts for newlines)
                test_chunk = current_chunk + [line]
                test_content = "\n".join(test_chunk)
                actual_tokens = self.count_tokens(test_content)

                if actual_tokens <= safe_max_tokens:
                    current_chunk.append(line)
                else:
                    if current_chunk:
                        chunk = self._create_chunk(
                            content="\n".join(current_chunk),
                            repo_id=repo_id,
                            file_path=file_path,
                            language=language,
                            start_line=chunk_start + 1,
                            end_line=i,
                            symbols_defined=[],
                            symbols_referenced=[],
                            commit_sha=commit_sha,
                        )
                        chunks.append(chunk)

                    current_chunk = [line]
                    chunk_start = i

        if current_chunk:
            chunk = self._create_chunk(
                content="\n".join(current_chunk),
                repo_id=repo_id,
                file_path=file_path,
                language=language,
                start_line=chunk_start + 1,
                end_line=len(lines),
                symbols_defined=[],
                symbols_referenced=[],
                commit_sha=commit_sha,
            )
            chunks.append(chunk)

        logger.debug(f"_split_by_lines: Created {len(chunks)} chunks")
        return chunks

    def _split_text_by_tokens(self, text: str) -> List[str]:
        """Split text into chunks that each fit within max_tokens.

        Uses the tokenizer directly to ensure accurate token counting
        and guarantees each chunk is under the limit.

        Args:
            text: Text to split (can be arbitrarily large).

        Returns:
            List of text chunks, each under max_tokens.
        """
        tokens = self._tokenizer.encode(text)
        total_tokens = len(tokens)

        if total_tokens <= self.max_tokens:
            return [text]

        chunks = []
        # Use 95% of max_tokens to leave some safety margin
        chunk_size = int(self.max_tokens * 0.95)

        for start in range(0, total_tokens, chunk_size):
            end = min(start + chunk_size, total_tokens)
            chunk_tokens = tokens[start:end]
            chunk_text = self._tokenizer.decode(chunk_tokens)
            chunks.append(chunk_text)

        logger.info(
            f"Split {total_tokens} tokens into {len(chunks)} chunks "
            f"(max {chunk_size} tokens each)"
        )
        return chunks

    def _create_chunk(
        self,
        content: str,
        repo_id: str,
        file_path: str,
        language: Language,
        start_line: int,
        end_line: int,
        symbols_defined: List[str],
        symbols_referenced: List[str],
        commit_sha: str,
    ) -> Chunk:
        """Create a Chunk object with deterministic ID based on content hash.

        The chunk ID follows the pattern: {file_path}:{start_line}-{end_line}:{content_hash}
        where content_hash is SHA1 of UTF-8 encoded content, truncated to 10 hex characters.
        This ensures idempotent upserts when re-indexing the same content.
        """
        content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
        chunk_id = f"{file_path}:{start_line}-{end_line}:{content_hash}"
        return Chunk(
            chunk_id=chunk_id,
            repo_id=repo_id,
            file_path=file_path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            content=content,
            symbols_defined=symbols_defined,
            symbols_referenced=symbols_referenced,
            commit_sha=commit_sha,
            created_at=datetime.now(UTC),
        )

    def _extract_references(
        self, content: str, symbols: List[SymbolInfo]
    ) -> List[str]:
        """Extract symbol references from content."""
        references = []
        symbol_names = {s.name for s in symbols}

        # Simple word boundary matching
        words = set(re.findall(r"\b\w+\b", content))
        for name in symbol_names:
            if name in words:
                references.append(name)

        return references

    def _find_uncovered_ranges(
        self, total_lines: int, covered_lines: set
    ) -> List[Tuple[int, int]]:
        """Find line ranges not covered by function chunks."""
        ranges = []
        start = None

        for i in range(total_lines):
            if i not in covered_lines:
                if start is None:
                    start = i
            else:
                if start is not None:
                    ranges.append((start, i))
                    start = None

        if start is not None:
            ranges.append((start, total_lines))

        return ranges

    def _detect_text_language(self, file_path: str) -> Language:
        """Detect language for text files."""
        ext = file_path.lower().split(".")[-1] if "." in file_path else ""
        mapping = {
            "md": Language.MARKDOWN,
            "yaml": Language.YAML,
            "yml": Language.YAML,
            "json": Language.JSON,
        }
        return mapping.get(ext, Language.UNKNOWN)

    def ensure_chunk_fits(self, chunk: Chunk) -> List[Chunk]:
        """Ensure a chunk fits within max_tokens, splitting if necessary.

        This is a public method that can be called on any chunk to guarantee
        it fits within the token limit. Useful for post-processing or
        re-validating chunks.

        Uses a safety margin (95% of max_tokens) to prevent OOM during encoding,
        as chunks right at the limit can still cause memory spikes.

        Args:
            chunk: The chunk to validate/split.

        Returns:
            List containing either the original chunk (if it fits) or
            multiple smaller chunks that each fit within max_tokens.
        """
        token_count = self.count_tokens(chunk.content)

        # Use 95% safety margin (same as _split_by_lines) to prevent OOM
        # Chunks right at the limit (e.g., 8023 tokens) can still cause memory spikes
        safe_max_tokens = int(self.max_tokens * 0.95)

        if token_count <= safe_max_tokens:
            return [chunk]

        logger.info(
            f"Chunk {chunk.chunk_id} exceeds safe max_tokens ({token_count} > {safe_max_tokens}, "
            f"limit={self.max_tokens}), splitting into smaller chunks"
        )

        # Determine splitting strategy based on language
        text_languages = {Language.MARKDOWN, Language.YAML, Language.JSON, Language.UNKNOWN}

        if chunk.language in text_languages:
            # Use text-based splitting for text
            sub_chunks = self._split_by_paragraphs(
                content=chunk.content,
                base_line=chunk.start_line - 1,
                repo_id=chunk.repo_id,
                file_path=chunk.file_path,
                language=chunk.language,
                commit_sha=chunk.commit_sha,
            )
        else:
            # Use line-based splitting for code
            sub_chunks = self._split_by_lines(
                content=chunk.content,
                repo_id=chunk.repo_id,
                file_path=chunk.file_path,
                language=chunk.language,
                commit_sha=chunk.commit_sha,
            )

        # Verify all sub_chunks are under the safe limit, use token-aware splitting as fallback
        final_chunks = []
        for sub_chunk in sub_chunks:
            sub_tokens = self.count_tokens(sub_chunk.content)
            if sub_tokens <= safe_max_tokens:
                final_chunks.append(sub_chunk)
            else:
                # Sub-chunk still too large, use token-aware splitting
                logger.warning(
                    f"Sub-chunk still exceeds safe max_tokens ({sub_tokens} > {safe_max_tokens}, "
                    f"limit={self.max_tokens}), using token-aware splitting"
                )
                text_parts = self._split_text_by_tokens(sub_chunk.content)
                for j, part in enumerate(text_parts):
                    part_chunk = self._create_chunk(
                        content=part,
                        repo_id=sub_chunk.repo_id,
                        file_path=sub_chunk.file_path,
                        language=sub_chunk.language,
                        start_line=sub_chunk.start_line,
                        end_line=sub_chunk.end_line,
                        symbols_defined=[],
                        symbols_referenced=[],
                        commit_sha=sub_chunk.commit_sha,
                    )
                    final_chunks.append(part_chunk)

        # Preserve original chunk metadata in final chunks
        result = []
        for i, sub_chunk in enumerate(final_chunks):
            # Create new chunk with updated ID and preserved metadata
            new_chunk = Chunk(
                chunk_id=f"{chunk.chunk_id}_part{i+1}",
                repo_id=sub_chunk.repo_id,
                file_path=sub_chunk.file_path,
                language=sub_chunk.language,
                start_line=sub_chunk.start_line,
                end_line=sub_chunk.end_line,
                content=sub_chunk.content,
                symbols_defined=chunk.symbols_defined if i == 0 else [],
                symbols_referenced=chunk.symbols_referenced,
                commit_sha=sub_chunk.commit_sha,
                created_at=chunk.created_at,
                chunk_type=chunk.chunk_type,
            )
            result.append(new_chunk)

        logger.info(f"Split chunk {chunk.chunk_id} into {len(result)} parts")
        return result
