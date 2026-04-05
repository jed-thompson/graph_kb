"""Prompt Manager for Graph KB RAG operations.

This module provides template loading and rendering for code-aware Q&A.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models.base import ContextItem
from ..models.enums import ContextItemType


class GraphKBPromptManager:
    """Manages prompt templates for Graph KB RAG operations.

    This class handles loading and rendering of prompt templates used
    for code-aware question answering with the graph knowledge base.
    """

    def __init__(self, templates_dir: Optional[str] = None):
        """Initialize the GraphKBPromptManager.

        Args:
            templates_dir: Directory containing prompt templates.
                          Defaults to the prompts directory in this package.
        """
        if templates_dir is None:
            templates_dir = str(Path(__file__).parent)

        self._templates_dir = templates_dir
        self._env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Cache loaded templates
        self._system_prompt: Optional[str] = None
        self._tool_descriptions: Optional[str] = None
        self._architecture_system_prompt: Optional[str] = None

    def get_system_prompt(self) -> str:
        """Get the system prompt for code-aware Q&A.

        Returns:
            The system prompt content.
        """
        if self._system_prompt is None:
            self._system_prompt = self._load_template("system_prompt.md")
        return self._system_prompt

    def get_tool_descriptions(self) -> str:
        """Get the tool descriptions for LLM function calling.

        Returns:
            The tool descriptions content.
        """
        if self._tool_descriptions is None:
            self._tool_descriptions = self._load_template("tool_descriptions.md")
        return self._tool_descriptions

    def get_architecture_system_prompt(self) -> str:
        """Get the system prompt for architecture analysis.

        Returns:
            The architecture analysis system prompt content.
        """
        if self._architecture_system_prompt is None:
            self._architecture_system_prompt = self._load_template(
                "architecture_analysis_system_prompt.md"
            )
        return self._architecture_system_prompt

    def render_rag_context(
        self,
        question: str,
        context_items: List[ContextItem],
    ) -> str:
        """Render the RAG context template with retrieved chunks and paths.

        Args:
            question: The user's question.
            context_items: List of context items from retrieval.

        Returns:
            Rendered context string ready for LLM input.
        """
        # Separate chunks, graph paths, and directory summaries
        chunks = []
        graph_paths = []
        directory_summaries = []

        for item in context_items:
            if item.type == ContextItemType.CHUNK:
                chunks.append({
                    "file_path": item.file_path,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "content": item.content,
                    "symbol": item.symbol,
                    "score": item.score or 0.0,
                    "language": self._detect_language(item.file_path),
                })
            elif item.type == ContextItemType.GRAPH_PATH:
                graph_paths.append({
                    "description": item.description,
                    "nodes": item.nodes or [],
                })
            elif item.type == ContextItemType.DIRECTORY_SUMMARY:
                if item.directory_summary:
                    directory_summaries.append({
                        "path": item.directory_summary.path,
                        "file_count": item.directory_summary.file_count,
                        "symbol_count": item.directory_summary.symbol_count,
                        "files": item.directory_summary.files,
                        "main_symbols": item.directory_summary.main_symbols,
                        "incoming_deps": item.directory_summary.incoming_deps,
                        "outgoing_deps": item.directory_summary.outgoing_deps,
                    })

        # Render template
        template = self._env.get_template("rag_context.md")
        return template.render(
            question=question,
            chunks=chunks,
            graph_paths=graph_paths,
            directory_summaries=directory_summaries,
        )

    def render_full_prompt(
        self,
        question: str,
        context_items: List[ContextItem],
        include_tools: bool = True,
    ) -> Dict[str, str]:
        """Render the full prompt with system prompt and context.

        Args:
            question: The user's question.
            context_items: List of context items from retrieval.
            include_tools: Whether to include tool descriptions.

        Returns:
            Dictionary with 'system' and 'user' prompt strings.
        """
        system_prompt = self.get_system_prompt()

        if include_tools:
            system_prompt += "\n\n" + self.get_tool_descriptions()

        user_prompt = self.render_rag_context(question, context_items)

        return {
            "system": system_prompt,
            "user": user_prompt,
        }

    def _load_template(self, filename: str) -> str:
        """Load a template file as raw text.

        Args:
            filename: Name of the template file.

        Returns:
            Template content as string.

        Raises:
            FileNotFoundError: If template file doesn't exist.
        """
        template_path = os.path.join(self._templates_dir, filename)
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    def _detect_language(self, file_path: Optional[str]) -> str:
        """Detect programming language from file path.

        Args:
            file_path: Path to the file.

        Returns:
            Language identifier for syntax highlighting.
        """
        if not file_path:
            return ""

        extension_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".go": "go",
            ".java": "java",
            ".rb": "ruby",
            ".rs": "rust",
            ".c": "c",
            ".cpp": "cpp",
            ".cs": "csharp",
            ".md": "markdown",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
            ".sh": "bash",
        }

        ext = os.path.splitext(file_path)[1].lower()
        return extension_map.get(ext, "")

    def list_templates(self) -> List[str]:
        """List all available template files.

        Returns:
            List of template filenames.
        """
        templates = []
        for filename in os.listdir(self._templates_dir):
            if filename.endswith(".md"):
                templates.append(filename)
        return sorted(templates)
