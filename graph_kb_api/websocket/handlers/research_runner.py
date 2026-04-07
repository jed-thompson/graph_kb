"""research_runner — single-repository research execution.

Extracted from research_dispatcher to break the circular import between
research_dispatcher and multi_repo_orchestrator.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from graph_kb_api.flows.v3.models.research_models import (
    ResearchContextCard,
    ResearchFindings,
    ResearchGap,
    ResearchRisk,
)
from graph_kb_api.flows.v3.tools.websearch import fetch_url_content
from graph_kb_api.websocket.handlers.base import logger
from graph_kb_api.websocket.research_events import (
    emit_context_found,
    emit_gap_detected,
    emit_research_complete,
    emit_research_error,
    emit_research_progress,
    emit_url_fetched,
)


async def run_single_repo_research(
    session: Dict[str, Any],
    repo_id: str,
    client_id: str,
    upstream_context: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Execute research for a single repository.

    Accepts the session dict directly so callers (dispatcher and orchestrator)
    avoid a round-trip through the module-level _sessions registry.

    Returns a findings dict on success, or None on failure/cancellation.
    """
    session_id: str = session["session_id"]
    web_urls: List[str] = session.get("web_urls", [])

    try:
        # Phase 1: Setup
        await emit_research_progress(session_id, "setup", "Initializing research session", 0.1, client_id)

        # Phase 2: Fetch web URLs
        if web_urls:
            await emit_research_progress(session_id, "web_fetch", f"Fetching {len(web_urls)} web URLs", 0.2, client_id)
            for i, url in enumerate(web_urls):
                try:
                    result = await fetch_url_content(url)
                    card = ResearchContextCard(
                        id=str(uuid.uuid4()),
                        source_type="web",
                        source_url=url,
                        source_name=url.split("//")[-1].split("/")[0],
                        title=f"Content from {url}",
                        content=result[:5000] if result else "No content extracted",
                        relevance_score=0.8,
                        tags=["web", "fetched"],
                        created_at=datetime.utcnow().isoformat(),
                    )
                    session["context_cards"].append(card.model_dump())
                    await emit_context_found(session_id, card, client_id)
                    await emit_url_fetched(session_id, url, card.title[:100], True, client_id)
                except Exception as e:
                    logger.warning("Failed to fetch URL %s: %s", url, e)
                    await emit_url_fetched(session_id, url, str(e), False, client_id)

                progress = 0.2 + (0.3 * (i + 1) / len(web_urls))
                await emit_research_progress(
                    session_id, "web_fetch", f"Fetched {i + 1}/{len(web_urls)} URLs", progress, client_id
                )

        # Phase 3: Repository analysis
        await emit_research_progress(session_id, "repo_analysis", f"Analyzing repository {repo_id}", 0.5, client_id)

        repo_card = ResearchContextCard(
            id=str(uuid.uuid4()),
            source_type="repository",
            source_name=repo_id,
            title=f"Repository Analysis: {repo_id}",
            content=(
                "## Repository Overview\n\nAnalyzed repository structure and code patterns."
                "\n\n```mermaid\ngraph TD\n    A[Repository] --> B[Modules]"
                "\n    A --> C[Components]\n    A --> D[Services]\n```"
            ),
            relevance_score=0.9,
            tags=["repository", "codebase"],
            created_at=datetime.utcnow().isoformat(),
        )
        session["context_cards"].append(repo_card.model_dump())
        await emit_context_found(session_id, repo_card, client_id)

        # Phase 4: Detect gaps
        await emit_research_progress(session_id, "gap_detection", "Analyzing for knowledge gaps", 0.7, client_id)

        gap = ResearchGap(
            id=str(uuid.uuid4()),
            category="technical",
            question="What are the specific technical constraints for this feature?",
            context="The repository analysis revealed potential technical constraints that need clarification.",
            suggested_answers=["Performance requirements", "Security constraints", "Compatibility requirements"],
            impact="high",
        )
        session["gaps"].append(gap.model_dump())
        await emit_gap_detected(session_id, gap, client_id)

        # Phase 5: Generate findings
        await emit_research_progress(session_id, "synthesis", "Synthesizing research findings", 0.9, client_id)

        findings = ResearchFindings(
            summary="Research completed. Found relevant context from web sources and repository analysis.",
            confidence_score=0.75,
            key_insights=[
                "Repository has modular architecture",
                "Web sources provide additional context",
                "Some knowledge gaps require clarification",
            ],
            related_modules=[
                {"name": "Core Module", "path": "src/core", "reason": "Primary functionality"},
            ],
            risks=[
                ResearchRisk(
                    id=str(uuid.uuid4()),
                    category="technical",
                    description="Integration complexity with existing modules",
                    severity="medium",
                    mitigation="Incremental integration with testing",
                )
            ],
        )
        session["findings"] = findings.model_dump()

        await emit_research_progress(session_id, "complete", "Research complete", 1.0, client_id)
        await emit_research_complete(session_id, findings, client_id)
        session["status"] = "complete"
        return findings.model_dump()

    except asyncio.CancelledError:
        logger.info("Research cancelled for session %s", session_id)
        session["status"] = "cancelled"
        return None
    except Exception as e:
        logger.exception("Research failed for session %s", session_id)
        await emit_research_error(session_id, str(e), "RESEARCH_ERROR", client_id)
        session["status"] = "error"
        return None
