"""
MultiRepoOrchestrator — coordinates multi-repo research execution.

Supports two strategies:
  - parallel_merge: all repos run concurrently (bounded by semaphore), findings merged
  - dependency_aware: repos run in topological order; upstream findings injected as context

Both strategies end with a cross-repo synthesis pass via RepoRelationshipAgent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from graph_kb_api.config.settings import settings
from graph_kb_api.flows.v3.agents.repo_relationship_agent import RepoRelationshipAgent
from graph_kb_api.flows.v3.models.research_models import (
    ResearchFindings,
    ResearchRisk,
)
from graph_kb_api.websocket.handlers.research_runner import run_single_repo_research
from graph_kb_api.websocket.research_events import (
    emit_hitl_pause,
    emit_repo_complete,
    emit_repo_failed,
    emit_repo_started,
    emit_research_complete,
    emit_research_error,
    emit_research_progress,
    emit_synthesis_complete,
    emit_synthesis_progress,
    emit_synthesis_started,
)

logger = logging.getLogger(__name__)

# HITL timeout in seconds (30 minutes)
_HITL_TIMEOUT_SECONDS = 1800


class MultiRepoOrchestrator:
    """Coordinates multi-repo research execution with HITL failure handling."""

    def __init__(self, session: Dict[str, Any], client_id: str) -> None:
        self._session = session
        self._client_id = client_id
        self._session_id: str = session["session_id"]
        self._repo_ids: List[str] = session["repo_ids"]
        self._relationships: List[Dict[str, Any]] = session.get("relationships", [])
        self._strategy: str = session.get("strategy", "parallel_merge")
        self._concurrency_limit: int = settings.multi_repo_concurrency_limit
        self._semaphore = asyncio.Semaphore(self._concurrency_limit)
        self._agent = RepoRelationshipAgent(client_id=client_id)

    # ── Public entry points ────────────────────────────────────────────────

    async def run_parallel_merge(self) -> None:
        """Run all repos concurrently (bounded by semaphore), then synthesise."""
        repo_ids = self._repo_ids
        total = len(repo_ids)
        all_findings: Dict[str, Any] = {}

        tasks = [
            self._run_repo_with_hitl(repo_id, idx, total, all_findings)
            for idx, repo_id in enumerate(repo_ids)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        if not all_findings:
            await emit_research_error(
                self._session_id,
                "All repositories failed — no findings to synthesise.",
                "ALL_REPOS_FAILED",
                self._client_id,
            )
            self._session["status"] = "error"
            return

        await self._run_synthesis(all_findings)

    async def run_dependency_aware(self) -> None:
        """Run repos in topological order (dependency edges only), then synthesise."""
        dep_edges = [
            r for r in self._relationships if r.get("relationship_type") == "dependency"
        ]
        levels = self._topological_levels(self._repo_ids, dep_edges)

        if levels is None:
            # Cycle detected — fall back to parallel_merge
            await emit_research_progress(
                self._session_id,
                "topology",
                "Cycle detected in dependency graph — falling back to parallel execution.",
                0.05,
                self._client_id,
            )
            await self.run_parallel_merge()
            return

        total = len(self._repo_ids)
        all_findings: Dict[str, Any] = {}

        for level_idx, level in enumerate(levels):
            upstream_context = self._build_upstream_context(all_findings)
            tasks = [
                self._run_repo_with_hitl(
                    repo_id,
                    self._repo_ids.index(repo_id),
                    total,
                    all_findings,
                    upstream_context=upstream_context if level_idx > 0 else None,
                )
                for repo_id in level
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        if not all_findings:
            await emit_research_error(
                self._session_id,
                "All repositories failed — no findings to synthesise.",
                "ALL_REPOS_FAILED",
                self._client_id,
            )
            self._session["status"] = "error"
            return

        await self._run_synthesis(all_findings)

    # ── Per-repo execution with HITL ───────────────────────────────────────

    async def _run_repo_with_hitl(
        self,
        repo_id: str,
        repo_index: int,
        total_repos: int,
        all_findings: Dict[str, Any],
        upstream_context: Optional[str] = None,
    ) -> None:
        """Run single-repo research with HITL pause on failure."""
        async with self._semaphore:
            while True:
                await emit_repo_started(
                    self._session_id, repo_id, repo_index, total_repos, self._client_id
                )
                findings = await self._run_single(repo_id, upstream_context)

                if findings is not None:
                    all_findings[repo_id] = findings
                    await emit_repo_complete(
                        self._session_id, repo_id, findings, self._client_id
                    )
                    return

                # Failure — emit and ask user
                error_msg = self._session.get("_last_error", {}).get(repo_id, "Research failed")
                error_phase = self._session.get("_last_phase", {}).get(repo_id, "unknown")

                await emit_repo_failed(
                    self._session_id, repo_id, error_msg, error_phase,
                    repo_index, total_repos, self._client_id,
                )
                await emit_hitl_pause(
                    self._session_id, repo_id, error_msg, error_phase, self._client_id
                )

                choice = await self._wait_for_hitl(repo_id)

                if choice == "retry":
                    continue  # loop again
                elif choice == "abort":
                    await emit_research_error(
                        self._session_id,
                        f"Research aborted by user after failure in {repo_id}.",
                        "USER_ABORT",
                        self._client_id,
                    )
                    self._session["status"] = "error"
                    # Cancel sibling tasks by raising
                    raise asyncio.CancelledError("User aborted")
                else:
                    # "continue" — skip this repo
                    logger.info("User chose to skip failed repo %s", repo_id)
                    return

    async def _run_single(
        self,
        repo_id: str,
        upstream_context: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run single-repo research via the shared runner module."""
        try:
            result = await run_single_repo_research(
                self._session, repo_id, self._client_id, upstream_context=upstream_context
            )
            return result
        except Exception as e:
            logger.exception("Repo %s failed: %s", repo_id, e)
            if "_last_error" not in self._session:
                self._session["_last_error"] = {}
            self._session["_last_error"][repo_id] = str(e)
            return None

    async def _wait_for_hitl(self, repo_id: str) -> str:
        """Wait for HITL response with 30-minute timeout. Returns 'continue'/'retry'/'abort'."""
        event = asyncio.Event()
        hitl_events: Dict[str, asyncio.Event] = self._session.setdefault("hitl_events", {})
        hitl_events[repo_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=_HITL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "HITL timeout for repo %s in session %s — auto-continuing.",
                repo_id,
                self._session_id,
            )
            return "continue"
        finally:
            hitl_events.pop(repo_id, None)

        return self._session.get("hitl_choice", "continue")

    # ── Synthesis pass ─────────────────────────────────────────────────────

    async def _run_synthesis(self, all_findings: Dict[str, Any]) -> None:
        """Run cross-repo synthesis via RepoRelationshipAgent."""
        await emit_synthesis_started(self._session_id, self._client_id)
        await emit_synthesis_progress(
            self._session_id, "merging", "Merging per-repository findings", 0.3, self._client_id
        )

        try:
            result = await self._agent.synthesize(all_findings, self._relationships)
            await emit_synthesis_progress(
                self._session_id, "analysing", "Analysing cross-repo relationships", 0.7, self._client_id
            )
            synthesis_dict = result.to_dict()
            self._session["cross_repo_synthesis"] = synthesis_dict
            await emit_synthesis_complete(self._session_id, synthesis_dict, self._client_id)
        except Exception as e:
            logger.exception("Synthesis failed for session %s", self._session_id)
            synthesis_dict = {
                "summary": f"Synthesis encountered an error: {e}",
                "api_contract_gaps": [],
                "cross_cutting_risks": [],
                "dependency_issues": [],
            }
            await emit_synthesis_complete(self._session_id, synthesis_dict, self._client_id)

        # Emit overall research.complete with merged findings
        summaries = [f.get("summary", "") for f in all_findings.values() if f.get("summary")]
        merged_summary = (
            synthesis_dict.get("summary", "")
            + ("\n\n" + " | ".join(summaries) if summaries else "")
        )

        merged_findings = ResearchFindings(
            summary=merged_summary,
            confidence_score=self._average_confidence(all_findings),
            key_insights=self._merge_key_insights(all_findings),
            related_modules=[],
            risks=[
                ResearchRisk(
                    id=r.get("id", "cross_risk"),
                    category=r.get("category", "cross_repo"),
                    description=r.get("description", ""),
                    severity=r.get("severity", "medium"),
                    mitigation=r.get("mitigation", ""),
                )
                for r in synthesis_dict.get("cross_cutting_risks", [])
            ],
        )
        self._session["findings"] = merged_findings.model_dump()
        self._session["status"] = "complete"

        await emit_research_progress(
            self._session_id, "complete", "Multi-repo research complete", 1.0, self._client_id
        )
        await emit_research_complete(self._session_id, merged_findings, self._client_id)

    # ── Topology helpers ───────────────────────────────────────────────────

    @staticmethod
    def _topological_levels(
        repo_ids: List[str],
        dep_edges: List[Dict[str, Any]],
    ) -> Optional[List[List[str]]]:
        """Kahn's algorithm — returns list of levels or None if cycle detected."""
        in_degree: Dict[str, int] = {r: 0 for r in repo_ids}
        adj: Dict[str, List[str]] = {r: [] for r in repo_ids}

        for edge in dep_edges:
            src = edge.get("source_repo_id", "")
            tgt = edge.get("target_repo_id", "")
            if src in adj and tgt in in_degree:
                adj[src].append(tgt)
                in_degree[tgt] += 1

        queue = [r for r in repo_ids if in_degree[r] == 0]
        levels: List[List[str]] = []
        visited = 0

        while queue:
            levels.append(list(queue))
            next_queue: List[str] = []
            for node in queue:
                for neighbor in adj[node]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
                visited += 1
            queue = next_queue

        if visited != len(repo_ids):
            return None  # Cycle detected
        return levels

    def _build_upstream_context(self, all_findings: Dict[str, Any]) -> Optional[str]:
        """Build upstream context string from completed findings."""
        if not all_findings:
            return None
        return self._agent.build_upstream_context(all_findings, "downstream")

    # ── Aggregate helpers ──────────────────────────────────────────────────

    @staticmethod
    def _average_confidence(all_findings: Dict[str, Any]) -> float:
        scores = [
            f.get("confidence_score", 0.5)
            for f in all_findings.values()
            if isinstance(f.get("confidence_score"), (int, float))
        ]
        return round(sum(scores) / len(scores), 3) if scores else 0.5

    @staticmethod
    def _merge_key_insights(all_findings: Dict[str, Any]) -> List[str]:
        insights: List[str] = []
        for repo_id, findings in all_findings.items():
            for insight in findings.get("key_insights", [])[:3]:
                insights.append(f"[{repo_id}] {insight}")
        return insights[:10]
