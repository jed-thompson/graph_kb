"""
Template management router.

Provides endpoints for uploading and listing prompt templates
that can be used as generation commands.
"""

import logging
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from graph_kb_api.dependencies import get_graph_kb_facade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["Templates"])


class TemplateMetadata(BaseModel):
    """Metadata for a prompt template."""

    name: str
    description: str


class TemplateListResponse(BaseModel):
    """Response containing a list of templates."""

    templates: List[TemplateMetadata]


def _extract_description(content: str) -> str:
    """Extract a description from template content.

    Uses the first non-empty, non-heading line as the description.
    Falls back to a generic message if nothing suitable is found.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Return the first meaningful line as description
        return stripped[:200]
    return "Prompt template"


def _template_name(filename: str) -> str:
    """Derive a human-readable template name from a filename.

    Strips the extension and replaces underscores/hyphens with spaces.
    """
    name = os.path.splitext(filename)[0]
    return name.replace("_", " ").replace("-", " ").title()


@router.post("/upload", response_model=TemplateMetadata)
async def upload_template(
    file: UploadFile,
    facade=Depends(get_graph_kb_facade),
):
    """Upload a new prompt template file.

    The template is stored in the prompt manager's templates directory
    and becomes available as a new generation command.
    """
    try:
        prompt_manager = facade.prompt_manager
        if prompt_manager is None:
            raise HTTPException(
                status_code=503,
                detail="Prompt manager is unavailable",
            )

        filename = file.filename or "untitled.md"
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")

        # Ensure the filename ends with .md
        if not filename.endswith(".md"):
            filename = filename + ".md"

        # Sanitise filename
        safe_name = "".join(
            c for c in filename if c.isalnum() or c in ("-", "_", ".")
        ).rstrip()
        if not safe_name:
            safe_name = "untitled.md"

        # Save to the prompt manager's templates directory
        template_path = os.path.join(prompt_manager._templates_dir, safe_name)
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(content)

        return TemplateMetadata(
            name=_template_name(safe_name),
            description=_extract_description(content),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload template: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload template: {e}")


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    facade=Depends(get_graph_kb_facade),
):
    """Return all available prompt templates with names and descriptions."""
    try:
        prompt_manager = facade.prompt_manager
        if prompt_manager is None:
            raise HTTPException(
                status_code=503,
                detail="Prompt manager is unavailable",
            )

        filenames = prompt_manager.list_templates()
        templates = []
        for fname in filenames:
            try:
                content = prompt_manager._load_template(fname)
                description = _extract_description(content)
            except FileNotFoundError:
                description = "Prompt template"

            templates.append(
                TemplateMetadata(
                    name=_template_name(fname),
                    description=description,
                )
            )

        return TemplateListResponse(templates=templates)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list templates: {e}")
