"""
Research Agent for Feature Spec Wizard Phase 2.

This agent conducts automated research and discovery:
- Scans the target repository for similar features
- Searches for related documents
- Identifies potential risks and blockers
- Detects information gaps requiring clarification

Outputs structured research findings for human review at Gate 6.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Mapping

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.agents.base_agent import AgentCapability

from graph_kb_api.flows.v3.agents.base_agent import AgentCapability as _AC
from graph_kb_api.flows.v3.agents.base_agent import BaseAgent
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.graph_kb.facade import GraphKBFacade
from graph_kb_api.utils.enhanced_logger import EnhancedLogger
from graph_kb_api.websocket.events import emit_phase_progress

logger = EnhancedLogger(__name__)


@dataclass
class ResearchGap:
    """Represents a gap in information that needs clarification."""

    id: str
    category: str  # "scope", "technical", "constraint", "stakeholder"
    question: str
    context: str
    suggested_answers: List[str]
    impact: str  # "high", "medium", "low"


@dataclass
class ResearchRisk:
    """Represents an identified risk."""

    id: str
    category: str  # "technical", "timeline", "resource", "dependency", "compliance"
    description: str
    severity: str  # "critical", "high", "medium", "low"
    mitigation: str
    related_gaps: List[str]


@dataclass
class ResearchFindings:
    """Structured output from the research agent."""

    # Codebase analysis
    similar_features: List[Dict[str, Any]]
    relevant_modules: List[Dict[str, str]]
    code_owners: List[Dict[str, str]]
    technical_debt: List[Dict[str, str]]

    # Document analysis
    related_specs: List[Dict[str, str]]
    api_contracts: List[Dict[str, str]]
    data_schemas: List[Dict[str, str]]
    business_rules: List[Dict[str, str]]

    # Risks and gaps
    risks: List[ResearchRisk]
    gaps: List[ResearchGap]

    # Summary
    summary: str
    confidence_score: float  # 0.0 - 1.0


# ── System Prompt (Librarian persona) ─────────────────────────────────────

_RESEARCHER_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("research")


class ResearchAgent(BaseAgent):
    """Agent that conducts research and discovery for the feature spec wizard.

    This agent analyzes the codebase and documents to provide context
    for the specification process. It identifies risks and gaps that
    need to be addressed.

    Used in Phase 2 of the wizard, before Gate 6 (Research Review).
    """

    def __init__(self, client_id: str | None = None) -> None:
        self.client_id: str | None = client_id

    @property
    def capability(self) -> "AgentCapability":
        """Return agent's capability description."""

        return _AC(
            agent_type="research_agent",
            supported_tasks=[
                "codebase_analysis",
                "document_search",
                "risk_identification",
                "gap_detection",
                "research_summary",
            ],
            required_tools=[],
            optional_tools=["search_code", "get_file_content"],
            description="Analyzes codebase and documents for feature spec context, identifies risks and gaps",
            system_prompt=_RESEARCHER_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute research phase.

        Args:
            task: Contains 'context' with all phase 1 data
            state: Current wizard state
            workflow_context: Application context for LLM/tools

        Returns:
            Dict with research findings and gaps
        """
        context = task.get("context", {})
        repo_id = context.get("target_repo_id")
        session_id = state.get("session_id")
        supplementary_docs = context.get("supporting_docs", [])
        user_explanation = context.get("user_explanation", "")

        # Emit progress
        await self._emit_progress(state, "starting_research", "Starting research phase...", 0)

        findings = ResearchFindings(
            similar_features=[],
            relevant_modules=[],
            code_owners=[],
            technical_debt=[],
            related_specs=[],
            api_contracts=[],
            data_schemas=[],
            business_rules=[],
            risks=[],
            gaps=[],
            summary="",
            confidence_score=0.0,
        )

        try:
            # Step 1: Analyze codebase
            await self._emit_progress(state, "scanning_codebase", "Scanning codebase for similar features...", 20)
            if repo_id:
                codebase_results = await self.analyze_codebase(repo_id, user_explanation, workflow_context)
                findings.similar_features = codebase_results.get("similar_features", [])
                findings.relevant_modules = codebase_results.get("relevant_modules", [])
                findings.code_owners = codebase_results.get("code_owners", [])
                findings.technical_debt = codebase_results.get("technical_debt", [])

            # Step 2: Search documents
            await self._emit_progress(state, "searching_documents", "Searching related documents...", 40)
            doc_results = await self._search_documents(
                user_explanation,
                supplementary_docs,
                workflow_context,
                repo_id=repo_id,
                session_id=session_id,
            )
            findings.related_specs = doc_results.get("related_specs", [])
            findings.api_contracts = doc_results.get("api_contracts", [])
            findings.data_schemas = doc_results.get("data_schemas", [])
            findings.business_rules = doc_results.get("business_rules", [])

            # Step 3: Identify risks
            await self._emit_progress(state, "identifying_risks", "Identifying potential risks...", 60)
            findings.risks: list[ResearchRisk] = await self._identify_risks(context, findings, workflow_context, state)

            # Step 4: Detect gaps
            await self._emit_progress(state, "detecting_gaps", "Detecting information gaps...", 80)
            findings.gaps: list[ResearchGap] = await self._detect_gaps(context, findings, workflow_context, state)

            # Step 5: Generate summary
            await self._emit_progress(state, "generating_summary", "Generating research summary...", 90)
            findings.summary: str = await self._generate_summary(findings, workflow_context)
            findings.confidence_score = self._calculate_confidence(findings)

            await self._emit_progress(state, "research_complete", "Research complete", 100)

        except Exception as e:
            logger.error(f"Research agent failed: {e}", exc_info=True)
            # Return partial findings with error
            findings.summary = f"Research partially completed. Error: {str(e)}"
            findings.confidence_score = 0.3

        return {
            "output": json.dumps(self._serialize_findings(findings)),
            "confidence_score": findings.confidence_score,
            "agent_type": "research_agent",
        }

    async def analyze_codebase(
        self,
        repo_id: str,
        user_explanation: str,
        workflow_context: WorkflowContext,
    ) -> Dict[str, Any]:
        """Analyze the target codebase for relevant information."""
        results = {
            "similar_features": [],
            "relevant_modules": [],
            "code_owners": [],
            "technical_debt": [],
        }

        try:
            # Use the graph KB to find similar features
            graph_store = getattr(workflow_context, "graph_store", None)
            if not graph_store:
                return results

            # Query for similar features
            # This would use the actual graph store queries
            # For now, return structured placeholders
            results["similar_features"] = await self._find_similar_features(repo_id, user_explanation, graph_store)

            # Find relevant modules
            results["relevant_modules"] = await self._find_relevant_modules(repo_id, user_explanation, graph_store)

        except Exception as e:
            logger.warning(f"Codebase analysis failed: {e}")

        return results

    async def _find_similar_features(
        self,
        repo_id: str,
        query: str,
        graph_store: Any,
    ) -> List[Dict[str, Any]]:
        """Find features in the codebase similar to what's being specified."""
        if not graph_store:
            logger.warning("graph_store is None, cannot find similar features")
            return []

        retrieval_service = getattr(graph_store, "retrieval_service", None)
        if not retrieval_service:
            logger.warning("retrieval_service not available on graph_store, cannot find similar features")
            return []

        try:
            import asyncio

            retrieve_fn = getattr(retrieval_service, "retrieve", None)
            if not retrieve_fn or not callable(retrieve_fn):
                logger.warning("retrieve method not available on retrieval_service")
                return []

            # retrieval_service.retrieve is synchronous but may block on I/O
            if asyncio.iscoroutinefunction(retrieve_fn):
                response = await retrieve_fn(repo_id, query)
            else:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, lambda: retrieve_fn(repo_id, query))

            results: List[Dict[str, Any]] = []
            seen_paths: set[str] = set()
            for item in getattr(response, "context_items", []) or []:
                file_path = getattr(item, "file_path", None)
                if not file_path or file_path in seen_paths:
                    continue
                seen_paths.add(file_path)
                results.append({
                    "name": getattr(item, "symbol", file_path) or file_path,
                    "file_path": file_path,
                    "description": (getattr(item, "content", "") or "")[:200].strip(),
                    "relevance": getattr(item, "score", 0.5) or 0.5,
                })
            return results[:10]
        except Exception as e:
            logger.warning(f"Failed to find similar features: {e}")
            return []

    async def _find_relevant_modules(
        self,
        repo_id: str,
        query: str,
        graph_store: Any,
    ) -> List[Dict[str, str]]:
        """Find modules that may be relevant to the feature."""
        if not graph_store:
            logger.warning("graph_store is None, cannot find relevant modules")
            return []

        query_service = getattr(graph_store, "query_service", None)
        if not query_service:
            logger.warning("query_service not available on graph_store, cannot find relevant modules")
            return []

        try:
            import asyncio

            get_arch_fn = getattr(query_service, "get_architecture", None)
            if not get_arch_fn or not callable(get_arch_fn):
                logger.warning("get_architecture method not available on query_service")
                return []

            # get_architecture is synchronous
            if asyncio.iscoroutinefunction(get_arch_fn):
                arch = await get_arch_fn(repo_id)
            else:
                loop = asyncio.get_event_loop()
                arch = await loop.run_in_executor(None, lambda: get_arch_fn(repo_id))

            modules: List[Dict[str, str]] = []
            for mod in getattr(arch, "modules", []) or []:
                module_path = mod.get("path", "") if isinstance(mod, dict) else str(mod)
                module_name = mod.get("name", module_path) if isinstance(mod, dict) else str(mod)
                if module_path:
                    modules.append({
                        "name": module_name,
                        "path": module_path,
                        "reason": f"Module {module_name} identified in repository architecture",
                    })
            return modules[:10]
        except Exception as e:
            logger.warning(f"Failed to find relevant modules: {e}")
            return []

    async def _search_documents(
        self,
        user_explanation: str,
        supplementary_docs: List[Dict[str, Any]],
        workflow_context: WorkflowContext,
        repo_id: str | None = None,
        session_id: str | None = None,
    ) -> Dict[str, Any]:
        """Search for related documents in the knowledge base."""
        results = {
            "related_specs": [],
            "api_contracts": [],
            "data_schemas": [],
            "business_rules": [],
        }

        try:
            graph_store: GraphKBFacade | None = workflow_context.graph_store
            if not graph_store:
                return results

            # Search for related specifications
            results["related_specs"] = await self._search_specs(
                user_explanation,
                graph_store,
                supplementary_docs=supplementary_docs,
                repo_id=repo_id,
                session_id=session_id,
            )

            # Search for API documentation
            results["api_contracts"] = await self._search_api_docs(
                user_explanation,
                graph_store,
                supplementary_docs=supplementary_docs,
                repo_id=repo_id,
                session_id=session_id,
            )

        except Exception as e:
            logger.warning(f"Document search failed: {e}")

        return results

    @staticmethod
    def _normalize_document_metadata(doc: Any) -> Dict[str, str] | None:
        """Normalize metadata service responses into a consistent document shape."""

        def _coerce(value: Any) -> str:
            if value is None:
                return ""
            if hasattr(value, "value"):
                return str(value.value)
            return str(value)

        def _get(field: str, default: Any = None) -> Any:
            if isinstance(doc, dict):
                return doc.get(field, default)
            return getattr(doc, field, default)

        normalized = {
            "doc_id": _coerce(_get("doc_id") or _get("id")),
            "name": _coerce(_get("original_name") or _get("name")),
            "file_path": _coerce(_get("file_path")),
            "category": _coerce(_get("category")),
            "collection_name": _coerce(_get("collection_name")),
            "parent_name": _coerce(_get("parent_name")),
            "status": _coerce(_get("status")),
        }
        if not any(normalized.values()):
            return None
        return normalized

    def _build_document_search_scopes(
        self,
        supplementary_docs: List[Dict[str, Any]] | None,
        repo_id: str | None,
        session_id: str | None,
    ) -> List[Dict[str, str]]:
        """Build workflow-scoped metadata filters.

        Research document lookups must remain scoped to the active workflow
        instead of scanning the global document catalog.
        """

        scopes: List[Dict[str, str]] = []
        seen_scopes: set[tuple[str, str]] = set()

        def _add_scope(*, parent_name: str = "", collection_name: str = "") -> None:
            scope = {
                "parent_name": parent_name.strip(),
                "collection_name": collection_name.strip(),
            }
            if not scope["parent_name"] and not scope["collection_name"]:
                return
            key = (scope["parent_name"], scope["collection_name"])
            if key in seen_scopes:
                return
            seen_scopes.add(key)
            scopes.append(scope)

        for raw_doc in supplementary_docs or []:
            normalized = self._normalize_document_metadata(raw_doc)
            if not normalized:
                continue
            _add_scope(
                parent_name=normalized.get("parent_name", ""),
                collection_name=normalized.get("collection_name", ""),
            )

        if session_id:
            _add_scope(parent_name=session_id)
        if repo_id:
            _add_scope(parent_name=repo_id)

        return scopes

    async def _list_scoped_documents(
        self,
        graph_store: Any,
        supplementary_docs: List[Dict[str, Any]] | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
    ) -> List[Dict[str, str]]:
        """Load workflow-scoped documents from the metadata store."""
        if not graph_store:
            logger.warning("graph_store is None, cannot search documents")
            return []

        metadata_store = getattr(graph_store, "metadata_store", None)
        if not metadata_store:
            logger.warning("metadata_store not available on graph_store, cannot search documents")
            return []

        scopes = self._build_document_search_scopes(supplementary_docs, repo_id, session_id)
        if not scopes:
            logger.info(
                "Skipping metadata document search because no workflow-scoped filters were available"
            )
            return []

        try:
            import asyncio

            list_docs_fn = getattr(metadata_store, "list_documents", None)
            if not list_docs_fn or not callable(list_docs_fn):
                logger.warning("list_documents method not available on metadata_store")
                return []

            normalized_docs: List[Dict[str, str]] = []
            seen_docs: set[str] = set()

            for scope in scopes:
                list_kwargs = {
                    "status": "completed",
                    "limit": 20,
                    "parent_name": scope.get("parent_name"),
                    "collection_name": scope.get("collection_name"),
                }

                try:
                    if asyncio.iscoroutinefunction(list_docs_fn):
                        docs = await list_docs_fn(**list_kwargs)
                    else:
                        loop = asyncio.get_event_loop()
                        docs = await loop.run_in_executor(
                            None,
                            lambda kwargs=dict(list_kwargs): list_docs_fn(**kwargs),
                        )
                except TypeError:
                    logger.warning(
                        "metadata_store.list_documents must support workflow-scoped filters; "
                        "skipping unscoped document search"
                    )
                    return []

                for raw_doc in docs or []:
                    normalized = self._normalize_document_metadata(raw_doc)
                    if not normalized:
                        continue
                    doc_key = (
                        normalized.get("doc_id")
                        or normalized.get("file_path")
                        or normalized.get("name")
                    )
                    if not doc_key or doc_key in seen_docs:
                        continue
                    seen_docs.add(doc_key)
                    normalized_docs.append(normalized)

            return normalized_docs
        except Exception as e:
            logger.warning(f"Failed to search scoped documents: {e}")
            return []

    async def _search_specs(
        self,
        query: str,
        graph_store: Any,
        supplementary_docs: List[Dict[str, Any]] | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Search for related specifications."""
        docs = await self._list_scoped_documents(
            graph_store,
            supplementary_docs=supplementary_docs,
            repo_id=repo_id,
            session_id=session_id,
        )
        if not docs:
            return []

        try:
            results: List[Dict[str, Any]] = []
            query_lower = query.lower()
            for doc in docs:
                name = doc.get("name", "")
                category = doc.get("category", "")
                file_path = doc.get("file_path", "")

                is_spec = category and ("spec" in category.lower())
                name_match = name and any(word in name.lower() for word in query_lower.split() if len(word) > 3)
                if is_spec or name_match:
                    results.append({
                        "name": name,
                        "file_path": file_path,
                        "category": category,
                        "description": f"Document: {name}",
                        "relevance": 0.7 if is_spec else 0.5,
                    })

            return results[:10]
        except Exception as e:
            logger.warning(f"Failed to search specs: {e}")
            return []

    async def _search_api_docs(
        self,
        query: str,
        graph_store: Any,
        supplementary_docs: List[Dict[str, Any]] | None = None,
        repo_id: str | None = None,
        session_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Search for API documentation."""
        docs = await self._list_scoped_documents(
            graph_store,
            supplementary_docs=supplementary_docs,
            repo_id=repo_id,
            session_id=session_id,
        )
        if not docs:
            return []

        try:
            results: List[Dict[str, Any]] = []
            query_terms = [w for w in query.lower().split() if len(w) > 3]
            for doc in docs:
                name = doc.get("name", "")
                category = doc.get("category", "")
                file_path = doc.get("file_path", "")

                # Filter to API-like documents and match against query
                is_api = category and ("api" in category.lower())
                name_match = name and any(
                    term in name.lower() for term in ["api", "endpoint", "route", "contract"]
                )
                query_match = name and query_terms and any(
                    term in name.lower() for term in query_terms
                )
                if is_api or name_match or query_match:
                    results.append({
                        "name": name,
                        "file_path": file_path,
                        "category": category,
                        "description": f"API document: {name}",
                        "relevance": 0.7 if is_api else 0.5,
                    })

            return results[:10]
        except Exception as e:
            logger.warning(f"Failed to search API docs: {e}")
            return []

    async def _identify_risks(
        self,
        context: Dict[str, Any],
        findings: ResearchFindings,
        workflow_context: WorkflowContext,
        state: Mapping[str, Any],
    ) -> List[ResearchRisk]:
        """Identify potential risks based on research."""
        risks = []
        llm: LLMService = workflow_context.require_llm

        all_tools = state.get("available_tools", [])
        assigned_tools: list[Any] = [t for t in all_tools if t.name in self.capability.optional_tools]

        try:
            prompt: str = self._build_risk_prompt(context, findings)
            response = await llm.bind_tools(assigned_tools).ainvoke(prompt)
            risks: list[ResearchRisk] = self._parse_risks(str(response.content))
        except Exception as e:
            logger.warning(f"LLM risk detection failed: {e}")
            risks: list[ResearchRisk] = self._basic_risk_detection(context, findings)

        return risks

    def _basic_risk_detection(
        self,
        context: Dict[str, Any],
        findings: ResearchFindings,
    ) -> List[ResearchRisk]:
        """Basic rule-based risk detection."""
        risks = []
        constraints = context.get("constraints", {})
        # constraints may be a plain string from the context form or a dict
        if isinstance(constraints, str):
            constraints = {"raw": constraints}

        # Check timeline risk
        if constraints.get("hard_deadline"):
            risks.append(
                ResearchRisk(
                    id="risk_timeline",
                    category="timeline",
                    description="Hard deadline specified - schedule risk",
                    severity="high",
                    mitigation="Consider phased delivery with MVP first",
                    related_gaps=[],
                )
            )

        # Check team size
        team_size = constraints.get("team_size", 0)
        if team_size and team_size < 2:
            risks.append(
                ResearchRisk(
                    id="risk_resource",
                    category="resource",
                    description="Small team size may impact delivery",
                    severity="medium",
                    mitigation="Consider scope reduction or timeline extension",
                    related_gaps=[],
                )
            )

        return risks

    async def _detect_gaps(
        self,
        context: Dict[str, Any],
        findings: ResearchFindings,
        workflow_context: WorkflowContext,
        state: Mapping[str, Any],
    ) -> List[ResearchGap]:
        """Detect information gaps that need clarification."""
        gaps = []
        llm: LLMService = workflow_context.require_llm

        all_tools = state.get("available_tools", [])
        assigned_tools: list[Any] = [t for t in all_tools if t.name in self.capability.optional_tools]

        try:
            prompt: str = self._build_gap_prompt(context, findings)
            response = await llm.bind_tools(assigned_tools).ainvoke(prompt)
            gaps: list[ResearchGap] = self._parse_gaps(str(response.content))
        except Exception as e:
            logger.warning(f"LLM gap detection failed: {e}")
            gaps: list[ResearchGap] = self._basic_gap_detection(context, findings)

        return gaps

    def _basic_gap_detection(
        self,
        context: Dict[str, Any],
        findings: ResearchFindings,
    ) -> List[ResearchGap]:
        """Basic gap detection based on missing context."""
        gaps = []
        constraints = context.get("constraints", {})
        # constraints may be a plain string from the context form or a dict
        if isinstance(constraints, str):
            constraints = {"raw": constraints}

        # Check for missing scope clarification
        if not constraints.get("required_tech"):
            gaps.append(
                ResearchGap(
                    id="gap_tech_stack",
                    category="technical",
                    question="What is the preferred technology stack for this feature?",
                    context="No specific tech stack requirements were provided",
                    suggested_answers=["Use existing stack", "Specific framework preference"],
                    impact="high",
                )
            )

        # Check for missing performance requirements
        if not constraints.get("max_latency_ms"):
            gaps.append(
                ResearchGap(
                    id="gap_performance",
                    category="constraint",
                    question="Are there specific performance requirements?",
                    context="No latency requirements specified",
                    suggested_answers=[
                        "Standard web performance (<500ms)",
                        "Real-time (<100ms)",
                        "No specific requirements",
                    ],
                    impact="medium",
                )
            )

        return gaps

    async def _generate_summary(
        self,
        findings: ResearchFindings,
        workflow_context: WorkflowContext,
    ) -> str:
        """Generate a summary of research findings."""
        summary_parts = []

        # Codebase findings
        if findings.similar_features:
            summary_parts.append(f"Found {len(findings.similar_features)} similar feature(s) in codebase")

        if findings.relevant_modules:
            summary_parts.append(f"Identified {len(findings.relevant_modules)} relevant module(s)")

        # Document findings
        if findings.related_specs:
            summary_parts.append(f"Found {len(findings.related_specs)} related specification(s)")

        # Risk summary
        critical_risks = [r for r in findings.risks if r.severity in ("critical", "high")]
        if critical_risks:
            summary_parts.append(f"⚠️ {len(critical_risks)} high/critical risk(s) identified")

        # Gap summary
        if findings.gaps:
            high_impact_gaps = [g for g in findings.gaps if g.impact == "high"]
            if high_impact_gaps:
                summary_parts.append(f"🔍 {len(high_impact_gaps)} high-impact gap(s) need clarification")

        if not summary_parts:
            return "Research completed. No significant findings or concerns."

        return "\n\n".join(summary_parts)

    def _calculate_confidence(self, findings: ResearchFindings) -> float:
        """Calculate confidence score based on findings completeness."""
        score = 0.5  # Base score

        # Adjust based on codebase analysis
        if findings.similar_features:
            score += 0.1
        if findings.relevant_modules:
            score += 0.1

        # Adjust based on document analysis
        if findings.related_specs:
            score += 0.1
        if findings.api_contracts:
            score += 0.05

        # Adjust based on gaps (more gaps = less confidence)
        high_impact_gaps = len([g for g in findings.gaps if g.impact == "high"])
        score -= high_impact_gaps * 0.1

        # Adjust based on risks (more risks = less confidence)
        critical_risks = len([r for r in findings.risks if r.severity in ("critical", "high")])
        score -= critical_risks * 0.05

        return max(0.1, min(1.0, score))

    async def _emit_progress(
        self,
        state: Mapping[str, Any],
        step: str,
        message: str,
        progress: int,
    ) -> None:
        """Emit progress event via WebSocket if available."""
        session_id = state.get("session_id")
        if not session_id:
            logger.debug(f"Research progress (no session): {step} - {message} ({progress}%)")
            return

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="research",
                step=step,
                message=message,
                progress_pct=progress / 100.0,
                client_id=self.client_id,
            )
        except Exception as e:
            logger.warning(f"Failed to emit research progress: {e}")

    def _build_risk_prompt(self, context: Dict[str, Any], findings: ResearchFindings) -> str:
        """Build prompt for risk identification."""
        prompt = f"""Analyze the following feature specification context and identify potential risks.

Context:
- User Explanation: {context.get("user_explanation", "Not provided")}
- Business Value: {context.get("business_value", "Not provided")}
- Constraints: {json.dumps(context.get("constraints", {}), indent=2)}

Research Findings:
- Similar Features: {len(findings.similar_features)} found
- Relevant Modules: {len(findings.relevant_modules)} found
- Related Specs: {len(findings.related_specs)} found

Identify risks in these categories:
1. Technical - complexity, dependencies, unknowns
2. Timeline - schedule feasibility, hard deadlines
3. Resource - team size, skills, availability
4. Dependency - external systems, third-party services
5. Compliance - security, regulatory requirements

For each risk, provide:
- category
- description
- severity (critical/high/medium/low)
- mitigation suggestion

Return as JSON array of risk objects."""
        return append_document_context_to_prompt(prompt, context)

    def _build_gap_prompt(self, context: Dict[str, Any], findings: ResearchFindings) -> str:
        """Build prompt for gap detection."""
        prompt = f"""Analyze the following feature specification context and identify missing information.

Context:
- User Explanation: {context.get("user_explanation", "Not provided")}
- Constraints: {json.dumps(context.get("constraints", {}), indent=2)}

Research Findings Summary:
- Similar features found: {len(findings.similar_features)}
- Risks identified: {len(findings.risks)}

Identify gaps where more information would help create a better specification:
1. Scope gaps - unclear boundaries or requirements
2. Technical gaps - missing technical details
3. Constraint gaps - unclear constraints or preferences
4. Stakeholder gaps - missing stakeholder input

For each gap, provide:
- category
- question to ask the user
- context for why this matters
- suggested answers (2-3 options)
- impact (high/medium/low)

Return as JSON array of gap objects."""
        return append_document_context_to_prompt(prompt, context)

    @staticmethod
    def _extract_json_array(text: str) -> list | None:
        """Extract the first balanced JSON array from LLM text.

        Handles nested brackets and markdown code fences by counting
        bracket depth rather than relying on a greedy regex.
        """
        start = text.find("[")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    def _parse_risks(self, response: str) -> List[ResearchRisk]:
        """Parse LLM response into Risk objects."""
        try:
            data = self._extract_json_array(response)
            if data:
                return [
                    ResearchRisk(
                        id=f"risk_{i}",
                        category=r.get("category", "technical"),
                        description=r.get("description", ""),
                        severity=r.get("severity", "medium"),
                        mitigation=r.get("mitigation", ""),
                        related_gaps=r.get("related_gaps", []),
                    )
                    for i, r in enumerate(data)
                ]
        except Exception as e:
            logger.warning(f"Failed to parse risks: {e}")
        return []

    def _parse_gaps(self, response: str) -> List[ResearchGap]:
        """Parse LLM response into Gap objects."""
        try:
            data = self._extract_json_array(response)
            if data:
                return [
                    ResearchGap(
                        id=f"gap_{i}",
                        category=g.get("category", "scope"),
                        question=g.get("question", ""),
                        context=g.get("context", ""),
                        suggested_answers=g.get("suggested_answers", []),
                        impact=g.get("impact", "medium"),
                    )
                    for i, g in enumerate(data)
                ]
        except Exception as e:
            logger.warning(f"Failed to parse gaps: {e}")
        return []

    def _serialize_findings(self, findings: ResearchFindings) -> Dict[str, Any]:
        """Serialize findings to dict for state storage."""
        return {
            "similar_features": findings.similar_features,
            "relevant_modules": findings.relevant_modules,
            "code_owners": findings.code_owners,
            "technical_debt": findings.technical_debt,
            "related_specs": findings.related_specs,
            "api_contracts": findings.api_contracts,
            "data_schemas": findings.data_schemas,
            "business_rules": findings.business_rules,
            "risks": [self._serialize_risk(r) for r in findings.risks],
            "gaps": [self._serialize_gap(g) for g in findings.gaps],
            "summary": findings.summary,
            "confidence_score": findings.confidence_score,
        }

    def _serialize_risk(self, risk: ResearchRisk) -> Dict[str, Any]:
        return {
            "id": risk.id,
            "category": risk.category,
            "description": risk.description,
            "severity": risk.severity,
            "mitigation": risk.mitigation,
            "related_gaps": risk.related_gaps,
        }

    def _serialize_gap(self, gap: ResearchGap) -> Dict[str, Any]:
        return {
            "id": gap.id,
            "category": gap.category,
            "question": gap.question,
            "context": gap.context,
            "suggested_answers": gap.suggested_answers,
            "impact": gap.impact,
        }
