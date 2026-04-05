"""
Roadmap Agent for Feature Spec Wizard Phase 3.

This agent creates implementation roadmaps:
- Breaks down the feature into implementation phases
- Identifies dependencies between components
- Creates timeline estimates based on complexity
- Proposes risk mitigation strategies
- Generates delivery milestones

Outputs a structured roadmap for human review at Gate 9.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional

from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.services.llm_service import LLMService
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("roadmap")


@dataclass
class RoadmapPhase:
    """Represents a phase in the implementation roadmap."""
    id: str
    name: str
    description: str
    order: int
    estimated_days: float
    dependencies: List[str]  # Phase IDs this depends on
    deliverables: List[str]
    risks: List[str]
    required_skills: List[str]
    status: str = "planned"  # planned, in_progress, blocked, completed


@dataclass
class RoadmapMilestone:
    """Represents a delivery milestone."""
    id: str
    name: str
    description: str
    target_date: Optional[str]
    phases: List[str]  # Phase IDs included in this milestone
    acceptance_criteria: List[str]
    priority: str  # must_have, should_have, nice_to_have


@dataclass
class RiskMitigation:
    """Represents a risk mitigation strategy."""
    risk_id: str
    risk_description: str
    severity: str  # critical, high, medium, low
    probability: str  # high, medium, low
    mitigation_strategy: str
    contingency_plan: str
    owner: str
    trigger_indicators: List[str]


@dataclass
class ImplementationRoadmap:
    """Complete implementation roadmap output."""
    phases: List[RoadmapPhase]
    milestones: List[RoadmapMilestone]
    risk_mitigations: List[RiskMitigation]
    total_estimated_days: float
    critical_path: List[str]  # Phase IDs on critical path
    parallel_opportunities: List[List[str]]  # Groups of phases that can run in parallel
    assumptions: List[str]
    summary: str


class RoadmapAgent(BaseAgent):
    """Agent that creates implementation roadmaps for the feature spec wizard.

    This agent takes the research findings and creates a structured
    implementation plan with phases, milestones, and risk mitigations.

    Used in Phase 3 of the wizard, before Gate 9 (Roadmap Review).
    """

    @property
    def capability(self) -> AgentCapability:
        """Return agent's capability description."""
        return AgentCapability(
            agent_type="roadmap_agent",
            supported_tasks=[
                "scope_analysis",
                "phase_generation",
                "milestone_creation",
                "risk_mitigation",
                "timeline_estimation",
            ],
            required_tools=[],
            optional_tools=["search_code", "get_file_content"],
            description="Creates implementation roadmaps with phases, milestones, and risk mitigations",
            system_prompt=_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute roadmap generation phase.

        Args:
            task: Contains 'context' with phase 1-2 data including research findings
            state: Current wizard state
            workflow_context: Application context for LLM/tools

        Returns:
            AgentResult with implementation roadmap and milestones
        """
        context = task.get("context", {})
        research_findings = context.get("research_findings", {})
        constraints = context.get("constraints", {})
        context.get("user_explanation", "")

        # Emit progress
        await self._emit_progress(state, "starting_roadmap", "Starting roadmap generation...", 0)

        roadmap = ImplementationRoadmap(
            phases=[],
            milestones=[],
            risk_mitigations=[],
            total_estimated_days=0.0,
            critical_path=[],
            parallel_opportunities=[],
            assumptions=[],
            summary="",
        )

        try:
            # Step 1: Analyze scope and complexity
            await self._emit_progress(state, "analyzing_scope", "Analyzing scope and complexity...", 15)
            complexity = await self._analyze_complexity(context, research_findings, workflow_context)

            # Step 2: Generate implementation phases
            await self._emit_progress(state, "generating_phases", "Generating implementation phases...", 30)
            roadmap.phases = await self._generate_phases(
                context, research_findings, complexity, workflow_context
            )

            # Step 3: Create milestones
            await self._emit_progress(state, "creating_milestones", "Creating delivery milestones...", 50)
            roadmap.milestones = await self._create_milestones(
                roadmap.phases, constraints, workflow_context
            )

            # Step 4: Develop risk mitigations
            await self._emit_progress(state, "developing_mitigations", "Developing risk mitigations...", 65)
            roadmap.risk_mitigations = await self._develop_risk_mitigations(
                research_findings, roadmap.phases, workflow_context
            )

            # Step 5: Calculate timeline and critical path
            await self._emit_progress(state, "calculating_timeline", "Calculating timeline and critical path...", 80)
            roadmap.total_estimated_days = self._calculate_total_days(roadmap.phases)
            roadmap.critical_path = self._identify_critical_path(roadmap.phases)
            roadmap.parallel_opportunities = self._find_parallel_opportunities(roadmap.phases)

            # Step 6: Apply constraints
            if constraints:
                roadmap = self._apply_constraints(roadmap, constraints)

            # Step 7: Generate summary
            await self._emit_progress(state, "generating_summary", "Generating roadmap summary...", 90)
            roadmap.assumptions = self._identify_assumptions(context, roadmap)
            roadmap.summary = self._generate_summary(roadmap)

            await self._emit_progress(state, "roadmap_complete", "Roadmap generation complete", 100)

        except Exception as e:
            logger.error(f"Roadmap agent failed: {e}", exc_info=True)
            roadmap.summary = f"Roadmap generation partially completed. Error: {str(e)}"

        return {
            "output": json.dumps(self._serialize_roadmap(roadmap)),
            "agent_draft": roadmap.summary,
            "agent_type": "roadmap_agent",
        }

    async def _analyze_complexity(
        self,
        context: Dict[str, Any],
        research_findings: Dict[str, Any],
        workflow_context: WorkflowContext | None,
    ) -> Dict[str, Any]:
        """Analyze the complexity of the feature implementation."""
        complexity = {
            "overall": "medium",
            "factors": [],
            "score": 0.5,
        }

        if not workflow_context or not workflow_context.llm:
            return self._basic_complexity_analysis(context, research_findings)

        try:
            llm: LLMService = workflow_context.llm  # type: ignore[assignment]
            prompt = self._build_complexity_prompt(context, research_findings)
            heading_marker = "\n## "
            if heading_marker in prompt:
                messages = [
                    {"role": "system", "content": prompt[: prompt.index(heading_marker)].strip()},
                    {"role": "user", "content": prompt[prompt.index(heading_marker):]},
                ]
            else:
                messages = [{"role": "user", "content": prompt}]
            response = await llm.ainvoke(messages)
            complexity = self._parse_complexity(response.content)
        except Exception as e:
            logger.warning(f"LLM complexity analysis failed: {e}")
            complexity = self._basic_complexity_analysis(context, research_findings)

        return complexity

    def _basic_complexity_analysis(
        self,
        context: Dict[str, Any],
        research_findings: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Basic rule-based complexity analysis."""
        factors = []
        score = 0.5

        # Check for integrations
        similar_features = research_findings.get("similar_features", [])
        if len(similar_features) > 3:
            factors.append("Multiple similar features exist - may indicate complexity")
            score += 0.1

        # Check for risks
        risks = research_findings.get("risks", [])
        critical_risks = [r for r in risks if r.get("severity") in ("critical", "high")]
        if critical_risks:
            factors.append(f"{len(critical_risks)} high/critical risks identified")
            score += 0.15 * len(critical_risks)

        # Check for gaps
        gaps = research_findings.get("gaps", [])
        high_impact_gaps = [g for g in gaps if g.get("impact") == "high"]
        if high_impact_gaps:
            factors.append(f"{len(high_impact_gaps)} high-impact gaps need clarification")
            score += 0.1 * len(high_impact_gaps)

        # Check constraints
        constraints = context.get("constraints", {})
        if constraints.get("hard_deadline"):
            factors.append("Hard deadline constraint")
        if constraints.get("max_latency_ms"):
            factors.append("Performance requirements")
            score += 0.1
        if constraints.get("compliance"):
            factors.append("Compliance requirements")
            score += 0.15

        overall = "low" if score < 0.4 else "medium" if score < 0.7 else "high"

        return {
            "overall": overall,
            "factors": factors,
            "score": min(1.0, score),
        }

    async def _generate_phases(
        self,
        context: Dict[str, Any],
        research_findings: Dict[str, Any],
        complexity: Dict[str, Any],
        workflow_context: WorkflowContext | None,
    ) -> List[RoadmapPhase]:
        """Generate implementation phases based on analysis."""
        phases = []

        if not workflow_context or not workflow_context.llm:
            return self._generate_default_phases(context, complexity)

        try:
            llm: LLMService = workflow_context.llm  # type: ignore[assignment]
            prompt = self._build_phases_prompt(context, research_findings, complexity)
            heading_marker = "\n## "
            if heading_marker in prompt:
                messages = [
                    {"role": "system", "content": prompt[: prompt.index(heading_marker)].strip()},
                    {"role": "user", "content": prompt[prompt.index(heading_marker):]},
                ]
            else:
                messages = [{"role": "user", "content": prompt}]
            response = await llm.ainvoke(messages)
            phases = self._parse_phases(response.content)
        except Exception as e:
            logger.warning(f"LLM phase generation failed: {e}")
            phases = self._generate_default_phases(context, complexity)

        return phases

    def _generate_default_phases(
        self,
        context: Dict[str, Any],
        complexity: Dict[str, Any],
    ) -> List[RoadmapPhase]:
        """Generate default implementation phases."""
        base_days = 5 if complexity["overall"] == "low" else 10 if complexity["overall"] == "medium" else 15

        phases = [
            RoadmapPhase(
                id="phase_foundation",
                name="Foundation & Setup",
                description="Project setup, infrastructure, and base architecture",
                order=1,
                estimated_days=base_days * 0.15,
                dependencies=[],
                deliverables=["Project structure", "Base configuration", "Development environment"],
                risks=["Environment configuration issues"],
                required_skills=["DevOps", "Backend"],
            ),
            RoadmapPhase(
                id="phase_core",
                name="Core Implementation",
                description="Main feature implementation with business logic",
                order=2,
                estimated_days=base_days * 0.35,
                dependencies=["phase_foundation"],
                deliverables=["Core functionality", "API endpoints", "Data models"],
                risks=["Scope creep", "Technical debt"],
                required_skills=["Backend", "Database"],
            ),
            RoadmapPhase(
                id="phase_integration",
                name="Integration & API",
                description="Integration with external systems and API finalization",
                order=3,
                estimated_days=base_days * 0.25,
                dependencies=["phase_core"],
                deliverables=["Integrations complete", "API documentation", "Test coverage"],
                risks=["Third-party dependencies", "API contract changes"],
                required_skills=["Integration", "Testing"],
            ),
            RoadmapPhase(
                id="phase_polish",
                name="Polish & Optimization",
                description="Performance optimization, error handling, and UX improvements",
                order=4,
                estimated_days=base_days * 0.15,
                dependencies=["phase_integration"],
                deliverables=["Performance benchmarks", "Error handling", "UX refinements"],
                risks=["Performance bottlenecks"],
                required_skills=["Performance", "UX"],
            ),
            RoadmapPhase(
                id="phase_delivery",
                name="Delivery & Documentation",
                description="Final testing, documentation, and deployment preparation",
                order=5,
                estimated_days=base_days * 0.10,
                dependencies=["phase_polish"],
                deliverables=["Documentation", "Deployment guide", "Release notes"],
                risks=["Documentation gaps"],
                required_skills=["Documentation", "QA"],
            ),
        ]

        return phases

    async def _create_milestones(
        self,
        phases: List[RoadmapPhase],
        constraints: Dict[str, Any],
        workflow_context: WorkflowContext | None,
    ) -> List[RoadmapMilestone]:
        """Create delivery milestones from phases."""
        if not phases:
            return []

        # Calculate milestone dates based on phases
        milestones = []
        cumulative_days = 0
        deadline = constraints.get("deadline")

        # MVP Milestone (first 2-3 phases)
        mvp_phases = [p.id for p in phases[:3]]
        mvp_days = sum(p.estimated_days for p in phases[:3])
        milestones.append(RoadmapMilestone(
            id="milestone_mvp",
            name="MVP Release",
            description="Minimum viable product with core functionality",
            target_date=self._calculate_target_date(cumulative_days, deadline),
            phases=mvp_phases,
            acceptance_criteria=[
                "Core feature works end-to-end",
                "Basic error handling in place",
                "Manual testing passed",
            ],
            priority="must_have",
        ))
        cumulative_days += mvp_days

        # Full Release Milestone
        full_phases = [p.id for p in phases[3:]]
        full_days = sum(p.estimated_days for p in phases[3:])
        milestones.append(RoadmapMilestone(
            id="milestone_full",
            name="Full Release",
            description="Complete feature with all enhancements",
            target_date=self._calculate_target_date(cumulative_days + full_days, deadline),
            phases=full_phases,
            acceptance_criteria=[
                "All functionality complete",
                "Performance meets requirements",
                "Documentation complete",
                "Automated tests passing",
            ],
            priority="must_have",
        ))

        # Add optional enhancement milestone if time permits
        if deadline:
            milestones.append(RoadmapMilestone(
                id="milestone_enhancements",
                name="Future Enhancements",
                description="Nice-to-have improvements for future iterations",
                target_date=None,
                phases=[],
                acceptance_criteria=[
                    "Prioritized backlog created",
                    "Enhancement specs documented",
                ],
                priority="nice_to_have",
            ))

        return milestones

    async def _develop_risk_mitigations(
        self,
        research_findings: Dict[str, Any],
        phases: List[RoadmapPhase],
        workflow_context: WorkflowContext | None,
    ) -> List[RiskMitigation]:
        """Develop risk mitigation strategies."""
        mitigations = []

        # Get risks from research findings
        risks = research_findings.get("risks", [])
        for i, risk in enumerate(risks):
            mitigation = RiskMitigation(
                risk_id=f"risk_{i}",
                risk_description=risk.get("description", "Unknown risk"),
                severity=risk.get("severity", "medium"),
                probability="medium",
                mitigation_strategy=risk.get("mitigation", "Monitor and address as needed"),
                contingency_plan="Escalate to stakeholder if risk materializes",
                owner="Project Lead",
                trigger_indicators=["Schedule delay", "Quality issues"],
            )
            mitigations.append(mitigation)

        # Add phase-specific risks
        for phase in phases:
            for risk_desc in phase.risks:
                mitigation = RiskMitigation(
                    risk_id=f"phase_risk_{phase.id}",
                    risk_description=risk_desc,
                    severity="medium",
                    probability="medium",
                    mitigation_strategy=f"Early identification and proactive management during {phase.name}",
                    contingency_plan=f"Allocate buffer time in {phase.name}",
                    owner="Phase Lead",
                    trigger_indicators=[f"{phase.name} delay", f"{phase.name} blockers"],
                )
                mitigations.append(mitigation)

        return mitigations

    def _calculate_total_days(self, phases: List[RoadmapPhase]) -> float:
        """Calculate total estimated days accounting for dependencies."""
        if not phases:
            return 0.0

        # Simple approach: sum of critical path phases
        # More sophisticated: topological sort with parallel execution
        return sum(p.estimated_days for p in phases)

    def _identify_critical_path(self, phases: List[RoadmapPhase]) -> List[str]:
        """Identify the critical path through phases."""
        if not phases:
            return []

        # For simple sequential phases, all are on critical path
        # More sophisticated: use CPM algorithm
        return [p.id for p in phases]

    def _find_parallel_opportunities(self, phases: List[RoadmapPhase]) -> List[List[str]]:
        """Find phases that can run in parallel."""
        opportunities = []

        # Build dependency graph
        {p.id: set(p.dependencies) for p in phases}

        # Find phases with same dependencies (can run in parallel)
        dep_groups: Dict[frozenset, List[str]] = {}
        for p in phases:
            deps = frozenset(p.dependencies)
            if deps not in dep_groups:
                dep_groups[deps] = []
            dep_groups[deps].append(p.id)

        # Groups with multiple phases can run in parallel
        for deps, phase_ids in dep_groups.items():
            if len(phase_ids) > 1:
                opportunities.append(phase_ids)

        return opportunities

    def _apply_constraints(
        self,
        roadmap: ImplementationRoadmap,
        constraints: Dict[str, Any],
    ) -> ImplementationRoadmap:
        """Apply constraints to the roadmap."""
        # Adjust for team size
        team_size = constraints.get("team_size", 1)
        if team_size > 1:
            # Can parallelize more
            for opp in roadmap.parallel_opportunities:
                if len(opp) > 1:
                    # Reduce total time for parallel phases
                    pass  # Complex calculation - simplified for now

        # Adjust for deadline
        deadline = constraints.get("deadline")
        hard_deadline = constraints.get("hard_deadline", False)
        if deadline and hard_deadline:
            # May need to reduce scope
            roadmap.assumptions.append("Scope may need reduction to meet hard deadline")

        # Adjust for tech constraints
        forbidden_tech = constraints.get("forbidden_tech", [])
        if forbidden_tech:
            roadmap.assumptions.append(f"Avoiding forbidden technologies: {', '.join(forbidden_tech)}")

        return roadmap

    def _identify_assumptions(
        self,
        context: Dict[str, Any],
        roadmap: ImplementationRoadmap,
    ) -> List[str]:
        """Identify assumptions made in the roadmap."""
        assumptions = [
            "Team has necessary skills for all phases",
            "No major scope changes during implementation",
            "Dependencies are available when needed",
            "Development environment is properly configured",
        ]

        constraints = context.get("constraints", {})
        if not constraints.get("team_size"):
            assumptions.append("Team size is adequate for the workload")

        if not constraints.get("max_budget_usd"):
            assumptions.append("Budget is not a constraint")

        return assumptions

    def _generate_summary(self, roadmap: ImplementationRoadmap) -> str:
        """Generate a summary of the roadmap."""
        parts = []

        parts.append(f"Implementation roadmap with {len(roadmap.phases)} phases")
        parts.append(f"Total estimated time: {roadmap.total_estimated_days:.1f} days")

        if roadmap.milestones:
            parts.append(f"{len(roadmap.milestones)} milestones defined")

        if roadmap.parallel_opportunities:
            parts.append(f"{len(roadmap.parallel_opportunities)} opportunities for parallel execution")

        critical_risks = [r for r in roadmap.risk_mitigations if r.severity in ("critical", "high")]
        if critical_risks:
            parts.append(f"⚠️ {len(critical_risks)} high/critical risks identified with mitigations")

        return " | ".join(parts)

    def _calculate_target_date(
        self,
        days_from_now: float,
        deadline: Optional[str],
    ) -> Optional[str]:
        """Calculate target date for a milestone."""
        if deadline:
            # Use the deadline as reference
            return deadline

        # Calculate from today
        target = datetime.now() + timedelta(days=days_from_now)
        return target.strftime("%Y-%m-%d")

    async def _emit_progress(
        self,
        state: Mapping[str, Any],
        step: str,
        message: str,
        progress: int,
    ) -> None:
        """Emit progress event."""
        logger.debug(f"Roadmap progress: {step} - {message} ({progress}%)")

    # Prompt building methods

    def _build_complexity_prompt(
        self,
        context: Dict[str, Any],
        research_findings: Dict[str, Any],
    ) -> str:
        """Build prompt for complexity analysis."""
        prompt = f"""Analyze the complexity of implementing this feature.

Feature: {context.get('user_explanation', 'Not provided')}
Constraints: {json.dumps(context.get('constraints', {}), indent=2)}

Research Findings:
- Similar features: {len(research_findings.get('similar_features', []))} found
- Risks: {len(research_findings.get('risks', []))} identified
- Gaps: {len(research_findings.get('gaps', []))} need clarification

Assess complexity:
1. Overall level (low/medium/high)
2. Specific complexity factors
3. Score from 0.0 to 1.0

Return as JSON with: overall, factors (array), score"""
        return append_document_context_to_prompt(prompt, context)

    def _build_phases_prompt(
        self,
        context: Dict[str, Any],
        research_findings: Dict[str, Any],
        complexity: Dict[str, Any],
    ) -> str:
        """Build prompt for phase generation."""
        prompt = f"""Create implementation phases for this feature.

Feature: {context.get('user_explanation', 'Not provided')}
Complexity: {complexity['overall']} ({complexity['score']})
Similar Features: {len(research_findings.get('similar_features', []))}

Create 4-7 implementation phases. For each phase provide:
- id: unique identifier (e.g., "phase_1")
- name: short name
- description: 1-2 sentence description
- estimated_days: number of days (float)
- dependencies: array of phase ids this depends on
- deliverables: array of expected deliverables
- risks: array of specific risks
- required_skills: array of skills needed

Return as JSON array of phase objects."""
        return append_document_context_to_prompt(prompt, context)

    # Parsing methods

    def _parse_complexity(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into complexity analysis."""
        try:
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "overall": data.get("overall", "medium"),
                    "factors": data.get("factors", []),
                    "score": float(data.get("score", 0.5)),
                }
        except Exception as e:
            logger.warning(f"Failed to parse complexity: {e}")
        return {"overall": "medium", "factors": [], "score": 0.5}

    def _parse_phases(self, response: str) -> List[RoadmapPhase]:
        """Parse LLM response into Phase objects."""
        try:
            import re
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                phases = []
                for i, p in enumerate(data):
                    phases.append(RoadmapPhase(
                        id=p.get("id", f"phase_{i}"),
                        name=p.get("name", f"Phase {i+1}"),
                        description=p.get("description", ""),
                        order=i + 1,
                        estimated_days=float(p.get("estimated_days", 5)),
                        dependencies=p.get("dependencies", []),
                        deliverables=p.get("deliverables", []),
                        risks=p.get("risks", []),
                        required_skills=p.get("required_skills", []),
                    ))
                return phases
        except Exception as e:
            logger.warning(f"Failed to parse phases: {e}")
        return []

    # Serialization methods

    def _serialize_roadmap(self, roadmap: ImplementationRoadmap) -> Dict[str, Any]:
        """Serialize roadmap to dict for state storage."""
        return {
            "phases": [self._serialize_phase(p) for p in roadmap.phases],
            "milestones": [self._serialize_milestone(m) for m in roadmap.milestones],
            "risk_mitigations": [self._serialize_risk_mitigation(r) for r in roadmap.risk_mitigations],
            "total_estimated_days": roadmap.total_estimated_days,
            "critical_path": roadmap.critical_path,
            "parallel_opportunities": roadmap.parallel_opportunities,
            "assumptions": roadmap.assumptions,
            "summary": roadmap.summary,
        }

    def _serialize_phase(self, phase: RoadmapPhase) -> Dict[str, Any]:
        return {
            "id": phase.id,
            "name": phase.name,
            "description": phase.description,
            "order": phase.order,
            "estimated_days": phase.estimated_days,
            "dependencies": phase.dependencies,
            "deliverables": phase.deliverables,
            "risks": phase.risks,
            "required_skills": phase.required_skills,
            "status": phase.status,
        }

    def _serialize_milestone(self, milestone: RoadmapMilestone) -> Dict[str, Any]:
        return {
            "id": milestone.id,
            "name": milestone.name,
            "description": milestone.description,
            "target_date": milestone.target_date,
            "phases": milestone.phases,
            "acceptance_criteria": milestone.acceptance_criteria,
            "priority": milestone.priority,
        }

    def _serialize_risk_mitigation(self, rm: RiskMitigation) -> Dict[str, Any]:
        return {
            "risk_id": rm.risk_id,
            "risk_description": rm.risk_description,
            "severity": rm.severity,
            "probability": rm.probability,
            "mitigation_strategy": rm.mitigation_strategy,
            "contingency_plan": rm.contingency_plan,
            "owner": rm.owner,
            "trigger_indicators": rm.trigger_indicators,
        }
