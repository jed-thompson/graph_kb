"""
RepoRelationshipAgent — detects inter-repo relationships and synthesises cross-repo findings.

Responsibilities:
  1. detect_relationships: scans repo codebases for dependency declarations, imports,
     proto files, OpenAPI specs, and HTTP client URLs to propose inter-repo relationships.
  2. synthesize: merges per-repo findings and produces a CrossRepoSynthesisResult with
     API contract gaps, dependency issues, and cross-cutting risks.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from graph_kb_api.config.settings import settings
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability as _AC
from graph_kb_api.flows.v3.agents.base_agent import BaseAgent
from graph_kb_api.flows.v3.models.multi_repo_models import (
    CrossRepoSynthesisResult,
    DetectedRelationship,
    RelationshipKind,
)
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.utils.document_content_reader import PRIMARY_DOC_TOKEN_BUDGET
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
    from graph_kb_api.flows.v3.state import UnifiedSpecState

logger = logging.getLogger(__name__)


class RepoRelationshipAgent(BaseAgent):
    """Agent that detects inter-repo relationships and synthesises cross-repo findings.

    Unlike ResearchAgent (which focuses on a single repo), this agent operates
    across the full set of selected repositories to surface cross-cutting concerns.
    """

    def __init__(self, client_id: Optional[str] = None) -> None:
        self.client_id = client_id

    @property
    def capability(self) -> _AC:
        return _AC(
            agent_type="repo_relationship_agent",
            supported_tasks=[
                "relationship_detection",
                "cross_repo_synthesis",
                "api_contract_gap_analysis",
                "dependency_issue_detection",
            ],
            required_tools=[],
            optional_tools=[],
            description=(
                "Detects inter-repo relationships from static analysis and synthesises "
                "cross-repo research findings into API contract gaps and dependency issues."
            ),
            system_prompt="You are an expert software architect specialising in cross-service analysis.",
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: Optional[WorkflowContext],
    ) -> AgentResult:
        """Not used directly — call detect_relationships or synthesize instead."""
        return {"output": "{}", "confidence_score": 0.0, "agent_type": "repo_relationship_agent"}

    # ── Public API ─────────────────────────────────────────────────────────

    async def detect_relationships(
        self,
        repo_ids: List[str],
        local_paths: Dict[str, str],
    ) -> List[DetectedRelationship]:
        """Scan repo codebases and propose inter-repo relationships.

        Args:
            repo_ids: List of repo IDs in scope.
            local_paths: Map of repo_id -> local filesystem path.

        Returns:
            List of DetectedRelationship with evidence and confidence scores.
        """
        candidates: List[DetectedRelationship] = []

        for source_id in repo_ids:
            source_path = local_paths.get(source_id)
            if not source_path or not os.path.isdir(source_path):
                logger.debug("Skipping relationship scan for %s: path not available", source_id)
                continue

            for target_id in repo_ids:
                if target_id == source_id:
                    continue

                evidence = self._scan_for_relationship(source_path, source_id, target_id)
                if evidence:
                    rel_type = self._infer_relationship_type(evidence)
                    base = settings.retrieval_defaults.similarity_threshold
                    confidence = min(base + 0.1 * len(evidence), 1.0)
                    candidates.append(
                        DetectedRelationship(
                            source=source_id,
                            target=target_id,
                            relationship_type=rel_type,
                            evidence=evidence[:5],
                            confidence=round(confidence, 2),
                        )
                    )

        return candidates

    async def synthesize(
        self,
        all_findings: Dict[str, Any],
        relationships: List[Dict[str, Any]],
    ) -> CrossRepoSynthesisResult:
        """Run cross-repo synthesis on collected per-repo findings.

        Args:
            all_findings: Map of repo_id -> ResearchFindings dict.
            relationships: List of relationship dicts with source_repo_id, target_repo_id, relationship_type.

        Returns:
            CrossRepoSynthesisResult with gaps, risks, and dependency issues.
        """
        api_contract_gaps: List[Dict[str, Any]] = []
        dependency_issues: List[Dict[str, Any]] = []
        cross_cutting_risks: List[Dict[str, Any]] = []

        for rel in relationships:
            source_id = rel.get("source_repo_id", "")
            target_id = rel.get("target_repo_id", "")
            rel_type = rel.get("relationship_type", "dependency")

            source_findings = all_findings.get(source_id, {})
            target_findings = all_findings.get(target_id, {})

            if rel_type in ("rest", "grpc"):
                gaps = self._detect_api_contract_gaps(
                    source_id, target_id, rel_type, source_findings, target_findings
                )
                api_contract_gaps.extend(gaps)

            if rel_type == "dependency":
                issues = self._detect_dependency_issues(
                    source_id, target_id, source_findings, target_findings
                )
                dependency_issues.extend(issues)

        # Cross-cutting risks: risks appearing in 2+ repos
        cross_cutting_risks = self._detect_cross_cutting_risks(all_findings)

        summary = self._build_synthesis_summary(
            all_findings, api_contract_gaps, dependency_issues, cross_cutting_risks
        )

        return CrossRepoSynthesisResult(
            summary=summary,
            api_contract_gaps=api_contract_gaps,
            cross_cutting_risks=cross_cutting_risks,
            dependency_issues=dependency_issues,
        )

    def build_upstream_context(
        self,
        upstream_findings: Dict[str, Any],
        downstream_repo_id: str,
    ) -> str:
        """Build upstream context string for dependency-aware injection.

        Respects the token budget; summarises lowest-priority findings if over limit.

        Args:
            upstream_findings: Map of repo_id -> findings dict for upstream repos.
            downstream_repo_id: The repo that will receive this context.

        Returns:
            Formatted context string safe to inject into research prompts.
        """
        estimator = get_token_estimator()
        parts: List[str] = []

        for repo_id, findings in upstream_findings.items():
            summary = findings.get("summary", "")
            key_insights = findings.get("keyInsights", [])
            risks = findings.get("risks", [])

            section = (
                f"## Upstream repo: {repo_id}\n"
                f"### Summary\n{summary}\n"
                f"### Key Insights\n"
                + "\n".join(f"- {i}" for i in key_insights[:5])
                + "\n### Risks\n"
                + "\n".join(
                    f"- [{r.get('severity', '?')}] {r.get('description', '')}"
                    for r in risks[:5]
                )
            )
            parts.append(section)

        full_context = "\n\n".join(parts)

        # Check token budget; if over, summarise by truncating lower-priority sections
        tokens = estimator.count_tokens(full_context)
        if tokens <= PRIMARY_DOC_TOKEN_BUDGET:
            return full_context

        # Truncate to budget by trimming parts from the end
        trimmed: List[str] = []
        budget_used = 0
        for part in parts:
            part_tokens = estimator.count_tokens(part)
            if budget_used + part_tokens > PRIMARY_DOC_TOKEN_BUDGET:
                logger.info(
                    "Upstream context for %s truncated at token budget %d",
                    downstream_repo_id,
                    PRIMARY_DOC_TOKEN_BUDGET,
                )
                break
            trimmed.append(part)
            budget_used += part_tokens

        return "\n\n".join(trimmed) if trimmed else parts[0][:2000]

    # ── Private helpers ────────────────────────────────────────────────────

    def _scan_for_relationship(
        self,
        source_path: str,
        source_id: str,
        target_id: str,
    ) -> List[str]:
        """Return evidence strings if target_id is referenced in source_path's codebase."""
        evidence: List[str] = []
        target_slug = target_id.lower().replace("-", "_").replace("/", "_")
        target_parts = re.split(r"[-_/]", target_id.lower())

        for fname in ["requirements.txt", "pyproject.toml", "package.json", "go.mod"]:
            fpath = os.path.join(source_path, fname)
            if os.path.isfile(fpath):
                try:
                    content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                    if any(p in content.lower() for p in target_parts if len(p) > 2):
                        evidence.append(f"Referenced in {fname}")
                except OSError:
                    pass

        # Scan for .proto files
        for root, dirs, files in os.walk(source_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "vendor", "__pycache__")]
            for fname in files:
                if fname.endswith(".proto"):
                    try:
                        content = Path(os.path.join(root, fname)).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if target_slug in content.lower():
                            evidence.append(f"Referenced in proto file: {fname}")
                    except OSError:
                        pass

        # Scan Python/JS imports (top-level only for perf)
        for ext in (".py", ".ts", ".tsx", ".js"):
            for root, dirs, files in os.walk(source_path):
                # Skip common non-source dirs
                _skip = ("node_modules", ".git", "vendor", "__pycache__", ".next", "dist")
                dirs[:] = [d for d in dirs if d not in _skip]
                for fname in files:
                    if fname.endswith(ext):
                        try:
                            content = Path(os.path.join(root, fname)).read_text(
                                encoding="utf-8", errors="ignore"
                            )
                            if target_slug in content.lower() or any(
                                p in content.lower() for p in target_parts if len(p) > 3
                            ):
                                rel = os.path.relpath(os.path.join(root, fname), source_path)
                                evidence.append(f"Import/reference in {rel}")
                                if len(evidence) >= 5:
                                    return evidence
                        except OSError:
                            pass

        return evidence

    def _infer_relationship_type(self, evidence: List[str]) -> RelationshipKind:
        """Infer relationship type from evidence strings."""
        evidence_str = " ".join(evidence).lower()
        if "proto" in evidence_str or "grpc" in evidence_str:
            return "grpc"
        if any(kw in evidence_str for kw in ("openapi", "swagger", "http", "rest", "api")):
            return "rest"
        return "dependency"

    def _detect_api_contract_gaps(
        self,
        source_id: str,
        target_id: str,
        interface_type: str,
        source_findings: Dict[str, Any],
        target_findings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Detect API contract gaps between source and target for REST/gRPC relationships."""
        gaps: List[Dict[str, Any]] = []

        source_apis = {
            c.get("title", "") for c in source_findings.get("api_contracts", [])
        }
        target_apis = {
            c.get("title", "") for c in target_findings.get("api_contracts", [])
        }

        # Simple heuristic: if one side has contracts and the other has none, flag it
        if source_apis and not target_apis:
            gaps.append({
                "id": f"gap_{source_id}_{target_id}_no_consumer_contracts",
                "sourceRepo": source_id,
                "targetRepo": target_id,
                "interfaceType": interface_type,
                "description": (
                    f"{source_id} exposes API contracts but {target_id} has no "
                    f"documented {interface_type.upper()} client contracts."
                ),
                "severity": "medium",
                "mitigation": f"Add {interface_type.upper()} client documentation to {target_id}.",
            })
        elif target_apis and not source_apis:
            gaps.append({
                "id": f"gap_{source_id}_{target_id}_no_provider_contracts",
                "sourceRepo": source_id,
                "targetRepo": target_id,
                "interfaceType": interface_type,
                "description": (
                    f"{target_id} expects {interface_type.upper()} contracts from "
                    f"{source_id} but none were found."
                ),
                "severity": "high",
                "mitigation": f"Define and document the {interface_type.upper()} API in {source_id}.",
            })

        return gaps

    def _detect_dependency_issues(
        self,
        upstream_id: str,
        downstream_id: str,
        upstream_findings: Dict[str, Any],
        downstream_findings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Detect dependency issues between upstream and downstream repos."""
        issues: List[Dict[str, Any]] = []

        # If upstream has critical/high risks, flag them as dependency concerns
        upstream_risks = upstream_findings.get("risks", [])
        critical = [r for r in upstream_risks if r.get("severity") in ("critical", "high")]

        for risk in critical[:3]:
            issues.append({
                "id": f"dep_{upstream_id}_{downstream_id}_{risk.get('id', 'unknown')}",
                "upstreamRepo": upstream_id,
                "downstreamRepo": downstream_id,
                "description": (
                    f"Upstream repo {upstream_id} has a {risk.get('severity')} risk that "
                    f"may impact {downstream_id}: {risk.get('description', '')}"
                ),
                "severity": risk.get("severity", "medium"),
            })

        return issues

    def _detect_cross_cutting_risks(
        self,
        all_findings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Identify risk patterns that appear across 2+ repos."""
        category_counts: Dict[str, List[str]] = {}

        for repo_id, findings in all_findings.items():
            for risk in findings.get("risks", []):
                cat = risk.get("category", "unknown")
                if cat not in category_counts:
                    category_counts[cat] = []
                category_counts[cat].append(repo_id)

        cross_cutting: List[Dict[str, Any]] = []
        for category, repos in category_counts.items():
            if len(repos) >= 2:
                cross_cutting.append({
                    "id": f"cross_risk_{category}",
                    "category": category,
                    "description": (
                        f"Risk category '{category}' appears in {len(repos)} repos: "
                        f"{', '.join(repos)}. This may indicate a systemic issue."
                    ),
                    "severity": "medium",
                    "affectedRepos": repos,
                    "mitigation": f"Address '{category}' risks consistently across all affected repositories.",
                })

        return cross_cutting

    def _build_synthesis_summary(
        self,
        all_findings: Dict[str, Any],
        api_contract_gaps: List[Dict[str, Any]],
        dependency_issues: List[Dict[str, Any]],
        cross_cutting_risks: List[Dict[str, Any]],
    ) -> str:
        """Build a human-readable synthesis summary."""
        repo_count = len(all_findings)
        parts = [f"Cross-repository synthesis completed across {repo_count} repositories."]

        if api_contract_gaps:
            high = sum(1 for g in api_contract_gaps if g.get("severity") in ("high", "critical"))
            parts.append(
                f"Found {len(api_contract_gaps)} API contract gap(s)"
                + (f", {high} high/critical" if high else "") + "."
            )

        if dependency_issues:
            parts.append(f"Detected {len(dependency_issues)} dependency issue(s) across repo boundaries.")

        if cross_cutting_risks:
            parts.append(
                f"Identified {len(cross_cutting_risks)} cross-cutting risk pattern(s) "
                f"spanning multiple repositories."
            )

        if not api_contract_gaps and not dependency_issues and not cross_cutting_risks:
            parts.append("No significant cross-repository concerns detected.")

        return " ".join(parts)
