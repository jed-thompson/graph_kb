"""Agent Prompt Manager for loading agent persona templates.

Follows the GraphKBPromptManager pattern: Jinja2 FileSystemLoader,
Path-based directory resolution, cached template reads.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from jinja2 import Environment, FileSystemLoader


class AgentPromptManager:
    """Manages agent persona prompt templates.

    Loads markdown persona files from the personas/ directory tree,
    supports raw text loading and Jinja2 template rendering.
    """

    def __init__(self, personas_dir: Optional[str] = None) -> None:
        if personas_dir is None:
            personas_dir = str(Path(__file__).parent)

        self._personas_dir = personas_dir
        self._env = Environment(
            loader=FileSystemLoader(personas_dir),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._cache: Dict[str, str] = {}

    def get_prompt(self, name: str, subdir: str = "agents") -> str:
        """Load a persona prompt by name, with caching.

        Args:
            name: Prompt filename without extension (e.g., "architect").
            subdir: Subdirectory ("agents", "phases", "nodes").

        Returns:
            Raw prompt text.

        Raises:
            FileNotFoundError: If persona file doesn't exist.
        """
        cache_key = f"{subdir}/{name}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self._load_raw(name, subdir)
        return self._cache[cache_key]

    def render_prompt(
        self,
        name: str,
        subdir: str = "agents",
        **variables: object,
    ) -> str:
        """Load and render a Jinja2 persona template.

        Args:
            name: Template filename without extension.
            subdir: Subdirectory ("agents", "phases", "nodes").
            **variables: Variables to pass to Jinja2 rendering.

        Returns:
            Rendered prompt string.
        """
        template_path = f"{subdir}/{name}.md"
        template = self._env.get_template(template_path)
        return template.render(**variables)

    def _load_raw(self, name: str, subdir: str) -> str:
        """Load a template file as raw text."""
        rel_path = os.path.join(subdir, f"{name}.md")
        full_path = os.path.join(self._personas_dir, rel_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Persona template not found: {full_path}")

        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def clear_cache(self) -> None:
        """Clear the loaded prompt cache."""
        self._cache.clear()


_manager: Optional[AgentPromptManager] = None


def get_agent_prompt_manager() -> AgentPromptManager:
    """Get or create the module-level AgentPromptManager singleton."""
    global _manager
    if _manager is None:
        _manager = AgentPromptManager()
    return _manager
