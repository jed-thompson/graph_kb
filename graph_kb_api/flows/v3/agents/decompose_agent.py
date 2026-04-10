"""
Decompose Agent for Feature Spec Wizard Phase 4.

This agent breaks down the feature into implementable units:
- Creates user stories with acceptance criteria
- Estimates story complexity and effort
- Identifies dependencies between stories
- Maps stories to roadmap phases
- Generates task breakdowns

Outputs structured story cards for human review at Gate 11.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping

from deepagents import create_deep_agent
from langchain.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from graph_kb_api.context import AppContext
from graph_kb_api.core.llm import LLMService, LLMQuotaExhaustedError
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models import (
    AcceptanceCriterion,
    AgentResult,
    AgentTask,
    StoryMap,
    Task,
    UserStory,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.flows.v3.state.workflow_state import PlanData  # noqa: F401
from graph_kb_api.flows.v3.tools import get_all_tools
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt
from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig
from graph_kb_api.utils.enhanced_logger import EnhancedLogger
from graph_kb_api.websocket.plan_events import emit_phase_progress

logger = EnhancedLogger(__name__)

_SYSTEM_PROMPT: str = get_agent_prompt_manager().get_prompt("decompose")


class DecomposeAgent(BaseAgent):
    """Agent that decomposes features into user stories and tasks.

    This agent takes the roadmap and creates detailed user stories
    with acceptance criteria, estimates, and dependencies.

    Used in Phase 4 of the wizard, before Gate 11 (Decomposition Review).
    """

    def __init__(self, client_id: str | None = None) -> None:
        self.client_id = client_id

    @property
    def capability(self) -> AgentCapability:
        """Return agent's capability description."""
        return AgentCapability(
            agent_type="decompose_agent",
            supported_tasks=[
                "story_decomposition",
                "acceptance_criteria_generation",
                "effort_estimation",
                "dependency_mapping",
                "task_breakdown",
            ],
            required_tools=[],
            optional_tools=["search_code", "get_file_content"],
            description="Decomposes features into user stories, acceptance criteria, and tasks",
            system_prompt=_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute decomposition phase.

        Args:
            task: Contains 'context' with phase 1-3 data including roadmap
            state: Current wizard state
            workflow_context: Application context for LLM/tools

        Returns:
            Dict with story map and task breakdowns
        """
        assert workflow_context is not None, "DecomposeAgent requires a WorkflowContext"

        context = task.get("context", {})
        roadmap = context.get("roadmap", {})
        context.get("user_explanation", "")
        constraints = context.get("constraints", {})

        # Emit progress
        await self._emit_progress(state, "starting_decomposition", "Starting story decomposition...", 0)

        story_map = StoryMap(
            stories=[],
            tasks=[],
            total_story_points=0,
            dependency_graph={},
            phase_mapping={},
            summary="",
        )

        try:
            # Step 1: Analyze feature requirements
            await self._emit_progress(state, "analyzing_requirements", "Analyzing feature requirements...", 15)
            requirements: dict[str, Any] = await self._analyze_requirements(context, workflow_context)

            # Step 2: Generate user stories
            await self._emit_progress(state, "generating_stories", "Generating user stories...", 30)
            story_map.stories: list[UserStory] = await self._generate_stories(
                requirements, roadmap, constraints, context, workflow_context
            )

            # Step 3: Create acceptance criteria
            await self._emit_progress(state, "creating_criteria", "Creating acceptance criteria...", 50)
            story_map.stories: list[UserStory] = await self._add_acceptance_criteria(
                story_map.stories, context, workflow_context
            )

            # Step 4: Estimate story points
            await self._emit_progress(state, "estimating_stories", "Estimating story points...", 65)
            story_map.stories: list[UserStory] = self._estimate_stories(story_map.stories, roadmap)

            # Step 5: Generate task breakdowns
            await self._emit_progress(state, "generating_tasks", "Generating task breakdowns...", 80)
            story_map.tasks: list[Task] = await self._generate_tasks(story_map.stories, context, workflow_context)

            # Step 6: Build dependency graph
            await self._emit_progress(state, "building_dependencies", "Building dependency graph...", 90)
            story_map.dependency_graph: dict[str, list[str]] = self._build_dependency_graph(story_map.stories)
            story_map.phase_mapping: dict[str, list[str]] = self._build_phase_mapping(story_map.stories)
            story_map.total_story_points: int = sum(s.story_points for s in story_map.stories)
            story_map.summary: str = self._generate_summary(story_map)

            await self._emit_progress(state, "decomposition_complete", "Story decomposition complete", 100)

        except Exception as e:
            # Re-raise quota exhaustion so the node-level handler can emit
            # a proper error to the UI instead of silently degrading
            if isinstance(e, LLMQuotaExhaustedError) or (
                isinstance(e.__cause__, LLMQuotaExhaustedError) if e.__cause__ else False
            ):
                raise

            logger.error(f"Decompose agent failed: {e}", exc_info=True)
            story_map.summary = f"Decomposition partially completed. Error: {str(e)}"

        return AgentResult(
            output=json.dumps(self._serialize_story_map(story_map)),
            tokens=0,
            agent_type="decompose_agent",
        )

    # ── Agent persona registry for spec-section decomposition ─────

    AGENT_PERSONAS: Dict[str, Dict[str, Any]] = {
        "architect": {
            "description": "Senior software architect — system design, component boundaries, data flows, scalability",
            "section_types": ["system_architecture", "component_design", "data_flow", "scalability"],
        },
        "lead_engineer": {
            "description": "Lead engineer — API design, implementation details, error handling, contracts",
            "section_types": ["api_design", "implementation_plan", "error_handling", "interface_contracts"],
        },
        "research": {
            "description": "Research specialist — technology evaluation, external dependencies, integration research",
            "section_types": ["technology_evaluation", "external_dependencies", "integration_research"],
        },
        "code_generator": {
            "description": "Code generation specialist — code examples, schema definitions, configuration templates",
            "section_types": ["code_examples", "schema_definitions", "configuration"],
        },
        "code_analyst": {
            "description": "Codebase analyst — existing patterns, technical debt assessment, migration paths",
            "section_types": ["codebase_analysis", "technical_debt", "migration_strategy"],
        },
    }

    async def execute_spec_decomposition(
        self,
        task: AgentTask,
        state: Mapping[str, Any],
        workflow_context: WorkflowContext,
    ) -> AgentResult:
        """Decompose a specification into agent-persona-aligned section tasks.

        Unlike execute() which produces generic user stories, this method
        decomposes the spec itself into sections where each section is
        assigned to an agent persona that will research and draft it.

        Args:
            task: Contains 'context' with roadmap, research findings, user explanation
            state: Current workflow state
            workflow_context: Application context for LLM/tools

        Returns:
            AgentResult with spec_sections list in output
        """
        context = task.get("context", {})
        roadmap = context.get("roadmap", {})
        user_explanation = context.get("user_explanation", "")
        constraints = context.get("constraints", {})
        spec_name = context.get("spec_name", "")
        research_findings = context.get("research_findings", {})
        document_section_index = context.get("document_section_index", [])

        await self._emit_progress(state, "starting_spec_decomposition", "Decomposing spec into sections...", 0)

        spec_sections: List[Dict[str, Any]] = []

        llm: LLMService = workflow_context.require_llm

        # Step 1: Identify spec sections via LLM
        await self._emit_progress(state, "identifying_sections", "Identifying spec sections...", 25)

        prompt: str = self._build_spec_sections_prompt(
            spec_name=spec_name,
            user_explanation=user_explanation,
            roadmap=roadmap,
            constraints=constraints,
            research_findings=research_findings,
            context=context,
            document_section_index=document_section_index,
        )

        app_context: AppContext | None = workflow_context.app_context
        if app_context:
            retrieval_config: RetrievalConfig = app_context.get_retrieval_settings()
            tools: list[StructuredTool] = get_all_tools(retrieval_config)
        else:
            tools = []

        deep_agent = create_deep_agent(tools=tools, system_prompt=_SYSTEM_PROMPT, model=llm)

        repo_id = state.get("repo_id", "")
        agent_config: RunnableConfig = {"configurable": {"repo_id": repo_id}}

        response_chunk = await deep_agent.ainvoke({"messages": [HumanMessage(content=prompt)]}, config=agent_config)

        agent_messages = response_chunk.get("messages", [])
        if not agent_messages:
            logger.warning("Deep agent failed to yield messages. Attempting fallback basic LLM call.")
            response: AIMessage = await llm.ainvoke(prompt)
            raw_content = str(response.content if hasattr(response, "content") else response)
        else:
            final_message = agent_messages[-1]
            raw_content = str(final_message.content if hasattr(final_message, "content") else final_message)

        spec_sections: list[dict[str, Any]] = self._parse_spec_sections(raw_content)

        # Step 2: Assign agent personas to sections
        await self._emit_progress(state, "assigning_personas", "Assigning agent personas...", 50)
        spec_sections: list[dict[str, Any]] = self._assign_agent_personas(spec_sections)

        # Step 3: Build dependency graph between sections
        await self._emit_progress(state, "building_section_deps", "Building section dependencies...", 75)
        dependency_graph: dict[str, list[str]] = self._build_section_dependency_graph(spec_sections)

        await self._emit_progress(state, "spec_decomposition_complete", "Spec decomposition complete", 100)

        output = {
            "spec_sections": spec_sections,
            "dependency_graph": dependency_graph,
            "total_sections": len(spec_sections),
            "decomposition_type": "spec_section",
        }

        return AgentResult(
            output=json.dumps(output),
            tokens=0,
            agent_type="decompose_agent",
        )

    def _build_spec_sections_prompt(
        self,
        spec_name: str,
        user_explanation: str,
        roadmap: Dict[str, Any],
        constraints: Dict[str, Any],
        research_findings: Dict[str, Any],
        context: Dict[str, Any],
        document_section_index: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build prompt for LLM to identify spec sections."""
        phases = roadmap.get("phases", [])
        phase_info = [f"- {p.get('id')}: {p.get('name')} — {p.get('description', '')}" for p in phases]
        research_summary = research_findings.get("summary", "No research available")
        key_insights = research_findings.get("key_insights", [])

        persona_descriptions = "\n".join(
            f"- **{name}**: {info['description']}" for name, info in self.AGENT_PERSONAS.items()
        )

        phases_text = chr(10).join(phase_info) if phase_info else "No phases defined"
        constraints_text = json.dumps(constraints, indent=2) if isinstance(constraints, dict) else str(constraints) if constraints else "None"
        insights_text = json.dumps(key_insights, indent=2) if key_insights else "None"

        prompt = (
            "You are decomposing a feature specification "
            "into sections that specialized agents will "
            "research and draft.\n\n"
            "## Specification\n"
            f"Name: {spec_name}\n"
            f"Description: {user_explanation}\n\n"
            "## Roadmap Phases\n"
            f"{phases_text}\n\n"
            "## Constraints\n"
            f"{constraints_text}\n\n"
            "## Research Findings\n"
            f"Summary: {research_summary}\n"
            f"Key Insights: {insights_text}\n\n"
            "## Available Agent Personas\n"
            f"{persona_descriptions}\n\n"
        )

        # Add document section index for traceability.
        if document_section_index:
            doc_toc_lines = []
            for doc in document_section_index:
                role_label = doc.get("role", "supporting")
                doc_id = doc.get("doc_id", "")
                doc_toc_lines.append(f"\n### {doc['filename']} (id: {doc_id}, {role_label})")
                for sec in doc.get("sections", []):
                    doc_toc_lines.append(f"- {sec['heading']}")
            prompt += "## Available Document Sections\n"
            prompt += "".join(doc_toc_lines) + "\n\n"

        prompt += "\n" + get_agent_prompt_manager().get_prompt("decompose_spec_sections")

        return append_document_context_to_prompt(prompt, context)

    def _parse_spec_sections(self, response: str) -> List[Dict[str, Any]]:
        """Parse LLM response into spec section dicts."""
        try:
            json_match: re.Match[str] | None = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                sections = json.loads(json_match.group())
                # Validate required fields
                validated = []
                for s in sections:
                    validated.append(
                        {
                            "id": s.get("id", f"spec_section_{len(validated)}"),
                            "name": s.get("name", f"Section {len(validated) + 1}"),
                            "description": s.get("description", ""),
                            "spec_section": s.get("spec_section", "general"),
                            "relevant_docs": s.get("relevant_docs", []),
                            "section_type": "analysis_and_draft",
                            "agent_type": s.get("agent_type", "architect"),
                            "context_requirements": s.get("context_requirements", ["roadmap", "research_findings"]),
                            "dependencies": s.get("dependencies", []),
                            "priority": s.get("priority", "medium"),
                            "tools_required": ["llm"],
                        }
                    )
                return validated
        except Exception as e:
            logger.warning(f"Failed to parse spec sections: {e}")
        return []

    def _assign_agent_personas(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate and normalize agent persona assignments.

        Ensures each section has a valid agent_type from the persona registry.
        Falls back to 'architect' for unknown types.
        """
        valid_types = set(self.AGENT_PERSONAS.keys())
        for section in sections:
            if section.get("agent_type") not in valid_types:
                section["agent_type"] = "architect"
        return sections

    def _build_section_dependency_graph(self, sections: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Build dependency graph from spec sections."""
        section_ids = {s["id"] for s in sections}
        graph: Dict[str, List[str]] = {}
        for section in sections:
            # Only keep dependencies that reference existing section ids
            deps = [d for d in section.get("dependencies", []) if d in section_ids]
            graph[section["id"]] = deps
        return graph

    async def _analyze_requirements(
        self,
        context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> Dict[str, Any]:
        """Analyze feature requirements for story generation."""
        requirements = {
            "functional": [],
            "non_functional": [],
            "user_roles": [],
            "integration_points": [],
        }

        llm: LLMService = workflow_context.require_llm

        try:
            prompt: str = self._build_requirements_prompt(context)
            response: AIMessage = await llm.ainvoke(prompt)
            raw_content: str = response.content if isinstance(response.content, str) else str(response.content)
            requirements: dict[str, Any] = self._parse_requirements(raw_content)
        except Exception as e:
            logger.warning(f"LLM requirements analysis failed: {e}")
            requirements: dict[str, Any] = self._basic_requirements_analysis(context)

        return requirements

    def _basic_requirements_analysis(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Basic requirements analysis from context."""
        context.get("user_explanation", "")

        return {
            "functional": ["Core feature functionality"],
            "non_functional": ["Performance", "Security", "Reliability"],
            "user_roles": ["End User", "Administrator"],
            "integration_points": [],
        }

    async def _generate_stories(
        self,
        requirements: Dict[str, Any],
        roadmap: Dict[str, Any],
        constraints: Dict[str, Any],
        context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> List[UserStory]:
        """Generate user stories from requirements."""
        stories = []

        llm: LLMService = workflow_context.require_llm

        try:
            prompt: str = self._build_stories_prompt(requirements, roadmap, constraints, context)
            response: AIMessage = await llm.ainvoke(prompt)
            raw_content: str = response.content if isinstance(response.content, str) else str(response.content)
            stories: list[UserStory] = self._parse_stories(raw_content, roadmap)
        except Exception as e:
            logger.warning(f"LLM story generation failed: {e}")
            stories = self._generate_default_stories(requirements, roadmap)

        return stories

    def _generate_default_stories(
        self,
        requirements: Dict[str, Any],
        roadmap: Dict[str, Any],
    ) -> List[UserStory]:
        """Generate default user stories."""
        phases = roadmap.get("phases", [])

        # Create stories for each major area
        stories = [
            UserStory(
                id="story_setup",
                title="Project Setup and Configuration",
                description=(
                    "As a developer, I want proper project setup so that I can start implementing features efficiently."
                ),
                acceptance_criteria=[],
                story_points=3,
                priority="must_have",
                phase_id=phases[0]["id"] if phases else "phase_foundation",
                dependencies=[],
                technical_notes="Initial project structure and configuration",
                risks=["Configuration complexity"],
                labels=["setup", "foundation"],
            ),
            UserStory(
                id="story_data_model",
                title="Data Model Implementation",
                description=(
                    "As a developer, I want a complete data model so that the feature "
                    "can persist and retrieve data correctly."
                ),
                acceptance_criteria=[],
                story_points=5,
                priority="must_have",
                phase_id=phases[1]["id"] if len(phases) > 1 else "phase_core",
                dependencies=["story_setup"],
                technical_notes="Database schema and ORM models",
                risks=["Schema changes", "Migration complexity"],
                labels=["backend", "database"],
            ),
            UserStory(
                id="story_api",
                title="API Endpoint Implementation",
                description=(
                    "As a client application, I want REST API endpoints so that I can "
                    "interact with the feature programmatically."
                ),
                acceptance_criteria=[],
                story_points=8,
                priority="must_have",
                phase_id=phases[1]["id"] if len(phases) > 1 else "phase_core",
                dependencies=["story_data_model"],
                technical_notes="RESTful API design and implementation",
                risks=["API contract changes"],
                labels=["backend", "api"],
            ),
            UserStory(
                id="story_validation",
                title="Input Validation and Error Handling",
                description="As a user, I want clear error messages so that I can understand and fix input issues.",
                acceptance_criteria=[],
                story_points=3,
                priority="should_have",
                phase_id=phases[1]["id"] if len(phases) > 1 else "phase_core",
                dependencies=["story_api"],
                technical_notes="Validation logic and error responses",
                risks=["Edge cases missed"],
                labels=["backend", "validation"],
            ),
            UserStory(
                id="story_testing",
                title="Automated Test Coverage",
                description="As a developer, I want comprehensive tests so that I can confidently modify the codebase.",
                acceptance_criteria=[],
                story_points=5,
                priority="should_have",
                phase_id=phases[2]["id"] if len(phases) > 2 else "phase_integration",
                dependencies=["story_api", "story_validation"],
                technical_notes="Unit tests, integration tests, test fixtures",
                risks=["Test flakiness", "Coverage gaps"],
                labels=["testing", "quality"],
            ),
            UserStory(
                id="story_docs",
                title="Documentation",
                description=(
                    "As a developer, I want comprehensive documentation so that I can "
                    "understand and maintain the feature."
                ),
                acceptance_criteria=[],
                story_points=2,
                priority="should_have",
                phase_id=phases[-1]["id"] if phases else "phase_delivery",
                dependencies=["story_api"],
                technical_notes="API docs, README, inline documentation",
                risks=["Documentation becoming outdated"],
                labels=["documentation"],
            ),
        ]

        return stories

    async def _add_acceptance_criteria(
        self,
        stories: List[UserStory],
        context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> List[UserStory]:
        """Add acceptance criteria to each story."""
        llm: LLMService = workflow_context.require_llm

        for story in stories:
            try:
                prompt: str = self._build_criteria_prompt(story, context)
                response: AIMessage = await llm.ainvoke(prompt)
                raw_content: str = response.content if isinstance(response.content, str) else str(response.content)
                story.acceptance_criteria: list[AcceptanceCriterion] = self._parse_criteria(raw_content)
            except Exception as e:
                logger.warning(f"LLM criteria generation failed for {story.id}: {e}")
                story.acceptance_criteria: list[AcceptanceCriterion] = self._generate_default_criteria(story)

        return stories

    def _generate_default_criteria(self, story: UserStory) -> List[AcceptanceCriterion]:
        """Generate default acceptance criteria for a story."""
        return [
            AcceptanceCriterion(
                id=f"{story.id}_crit_1",
                description=f"Feature works as described in {story.title}",
                type="functional",
                verification="Manual testing and automated tests",
            ),
            AcceptanceCriterion(
                id=f"{story.id}_crit_2",
                description="Error cases are handled gracefully",
                type="edge_case",
                verification="Test error scenarios",
            ),
        ]

    def _estimate_stories(
        self,
        stories: List[UserStory],
        roadmap: Dict[str, Any],
    ) -> List[UserStory]:
        """Estimate story points based on complexity."""
        # Fibonacci sequence for story points
        fibonacci = [1, 2, 3, 5, 8, 13, 21]

        for story in stories:
            # Base estimation on complexity factors
            base_points = story.story_points

            # Adjust for dependencies
            if len(story.dependencies) > 2:
                base_points = min(21, base_points + 3)

            # Adjust for risks
            if len(story.risks) > 2:
                base_points = min(21, base_points + 2)

            # Snap to nearest Fibonacci number
            story.story_points = min(fibonacci, key=lambda x: abs(x - base_points))

        return stories

    async def _generate_tasks(
        self,
        stories: List[UserStory],
        context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> List[Task]:
        """Generate task breakdowns for stories."""
        tasks = []
        llm: LLMService = workflow_context.require_llm

        for story in stories:
            try:
                prompt: str = self._build_tasks_prompt(story, context)
                response: AIMessage = await llm.ainvoke(prompt)
                raw_content: str = response.content if isinstance(response.content, str) else str(response.content)
                story_tasks: list[Task] = self._parse_tasks(raw_content, story.id)
                tasks.extend(story_tasks)
            except Exception as e:
                logger.warning(f"LLM task generation failed for {story.id}: {e}")
                tasks.extend(self._generate_default_tasks(story))

        return tasks

    def _generate_default_tasks(self, story: UserStory) -> List[Task]:
        """Generate default tasks for a story."""
        base_hours = story.story_points * 2.5  # Rough estimate: 2.5 hours per point

        return [
            Task(
                id=f"{story.id}_task_1",
                story_id=story.id,
                title=f"Implement {story.title}",
                description=f"Core implementation for {story.title}",
                estimated_hours=base_hours * 0.6,
                assignee_type="backend",
                dependencies=[],
            ),
            Task(
                id=f"{story.id}_task_2",
                story_id=story.id,
                title=f"Write tests for {story.title}",
                description=f"Unit and integration tests for {story.title}",
                estimated_hours=base_hours * 0.3,
                assignee_type="qa",
                dependencies=[f"{story.id}_task_1"],
            ),
            Task(
                id=f"{story.id}_task_3",
                story_id=story.id,
                title=f"Review and refactor {story.title}",
                description=f"Code review and refactoring for {story.title}",
                estimated_hours=base_hours * 0.1,
                assignee_type="backend",
                dependencies=[f"{story.id}_task_2"],
            ),
        ]

    def _build_dependency_graph(self, stories: List[UserStory]) -> Dict[str, List[str]]:
        """Build dependency graph from stories."""
        graph = {}
        for story in stories:
            graph[story.id] = story.dependencies
        return graph

    def _build_phase_mapping(self, stories: List[UserStory]) -> Dict[str, List[str]]:
        """Build phase to stories mapping."""
        mapping: Dict[str, List[str]] = {}
        for story in stories:
            if story.phase_id not in mapping:
                mapping[story.phase_id] = []
            mapping[story.phase_id].append(story.id)
        return mapping

    def _generate_summary(self, story_map: StoryMap) -> str:
        """Generate summary of the story map."""
        parts = []

        parts.append(f"{len(story_map.stories)} user stories")
        parts.append(f"{story_map.total_story_points} total story points")
        parts.append(f"{len(story_map.tasks)} tasks")

        must_have = len([s for s in story_map.stories if s.priority == "must_have"])
        if must_have:
            parts.append(f"{must_have} must-have stories")

        # Count by phase
        for phase_id, story_ids in story_map.phase_mapping.items():
            parts.append(f"Phase {phase_id}: {len(story_ids)} stories")

        return " | ".join(parts)

    async def _emit_progress(
        self,
        state: Mapping[str, Any],
        step: str,
        message: str,
        progress: int,
    ) -> None:
        """Emit progress event via plan_events if available, otherwise log."""
        try:
            session_id = state.get("session_id", "")

            await emit_phase_progress(
                session_id=session_id,
                phase="planning",
                step=step,
                message=message,
                progress_pct=progress / 100.0,
                client_id=self.client_id,
            )
        except Exception:
            logger.debug(f"Decompose progress: {step} - {message} ({progress}%)")

    # Prompt building methods

    def _build_requirements_prompt(self, context: Dict[str, Any]) -> str:
        """Build prompt for requirements analysis."""
        prompt = f"""Analyze the feature requirements from this context.

Feature: {context.get("user_explanation", "Not provided")}
Constraints: {json.dumps(context.get("constraints", {}), indent=2) if isinstance(context.get("constraints", {}), dict) else str(context.get("constraints", {}))}

Extract and categorize:
1. Functional requirements (what the system must do)
2. Non-functional requirements (performance, security, etc.)
3. User roles who will interact with the feature
4. Integration points with other systems

Return as JSON with: functional (array), non_functional (array), user_roles (array), integration_points (array)"""
        return append_document_context_to_prompt(prompt, context)

    def _build_stories_prompt(
        self,
        requirements: Dict[str, Any],
        roadmap: Dict[str, Any],
        constraints: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """Build prompt for story generation."""
        phases = roadmap.get("phases", [])
        phase_info = [f"- {p.get('id')}: {p.get('name')}" for p in phases]

        prompt = f"""Create user stories for this feature.

Functional Requirements: {json.dumps(requirements.get("functional", []), indent=2)}
User Roles: {requirements.get("user_roles", [])}

Available Phases:
{chr(10).join(phase_info)}

Constraints: {json.dumps(constraints, indent=2) if isinstance(constraints, dict) else str(constraints)}

Create 5-10 user stories. For each story provide:
- id: unique identifier (e.g., "story_1")
- title: short title
- description: "As a <role>, I want <feature>, so that <benefit>"
- priority: must_have, should_have, or nice_to_have
- phase_id: which phase this belongs to
- dependencies: array of story ids this depends on (can be empty)
- technical_notes: implementation notes
- risks: array of specific risks
- labels: array of relevant labels

Return as JSON array of story objects."""
        return append_document_context_to_prompt(prompt, context)

    def _build_criteria_prompt(self, story: UserStory, context: Dict[str, Any]) -> str:
        """Build prompt for acceptance criteria generation."""
        prompt = f"""Create acceptance criteria for this user story.

Story: {story.title}
Description: {story.description}
Technical Notes: {story.technical_notes}

Create 3-5 acceptance criteria. For each criterion provide:
- id: unique identifier
- description: what must be true
- type: functional, non_functional, or edge_case
- verification: how to verify this criterion is met

Return as JSON array of criterion objects."""
        return append_document_context_to_prompt(prompt, context)

    def _build_tasks_prompt(self, story: UserStory, context: Dict[str, Any]) -> str:
        """Build prompt for task generation."""
        prompt = f"""Create technical tasks for this user story.

Story: {story.title}
Description: {story.description}
Story Points: {story.story_points}
Technical Notes: {story.technical_notes}

Create 2-4 technical tasks. For each task provide:
- id: unique identifier
- title: short title
- description: what needs to be done
- estimated_hours: hours estimate (float)
- assignee_type: backend, frontend, devops, qa, or documentation
- dependencies: array of task ids this depends on (can be empty)

Return as JSON array of task objects."""
        return append_document_context_to_prompt(prompt, context)

    # Parsing methods

    def _parse_requirements(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into requirements."""
        try:
            json_match: re.Match[str] | None = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.warning(f"Failed to parse requirements: {e}")
        return {
            "functional": [],
            "non_functional": [],
            "user_roles": [],
            "integration_points": [],
        }

    def _parse_stories(
        self,
        response: str,
        roadmap: Dict[str, Any],
    ) -> List[UserStory]:
        """Parse LLM response into Story objects."""
        try:
            json_match: re.Match[str] | None = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                phases = roadmap.get("phases", [])
                default_phase = phases[0]["id"] if phases else "phase_1"

                return [
                    UserStory(
                        id=s.get("id", f"story_{i}"),
                        title=s.get("title", f"Story {i + 1}"),
                        description=s.get("description", ""),
                        acceptance_criteria=[],
                        story_points=int(s.get("story_points", 5)),
                        priority=s.get("priority", "should_have"),
                        phase_id=s.get("phase_id", default_phase),
                        dependencies=s.get("dependencies", []),
                        technical_notes=s.get("technical_notes", ""),
                        risks=s.get("risks", []),
                        labels=s.get("labels", []),
                    )
                    for i, s in enumerate(data)
                ]
        except Exception as e:
            logger.warning(f"Failed to parse stories: {e}")
        return []

    def _parse_criteria(self, response: str) -> List[AcceptanceCriterion]:
        """Parse LLM response into AcceptanceCriterion objects."""
        try:
            json_match: re.Match[str] | None = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return [
                    AcceptanceCriterion(
                        id=c.get("id", f"crit_{i}"),
                        description=c.get("description", ""),
                        type=c.get("type", "functional"),
                        verification=c.get("verification", ""),
                    )
                    for i, c in enumerate(data)
                ]
        except Exception as e:
            logger.warning(f"Failed to parse criteria: {e}")
        return []

    def _parse_tasks(self, response: str, story_id: str) -> List[Task]:
        """Parse LLM response into Task objects."""
        try:
            json_match: re.Match[str] | None = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return [
                    Task(
                        id=t.get("id", f"{story_id}_task_{i}"),
                        story_id=story_id,
                        title=t.get("title", ""),
                        description=t.get("description", ""),
                        estimated_hours=float(t.get("estimated_hours", 4)),
                        assignee_type=t.get("assignee_type", "backend"),
                        dependencies=t.get("dependencies", []),
                    )
                    for i, t in enumerate(data)
                ]
        except Exception as e:
            logger.warning(f"Failed to parse tasks: {e}")
        return []

    # Serialization methods

    def _serialize_story_map(self, story_map: StoryMap) -> Dict[str, Any]:
        """Serialize story map to dict for state storage."""
        return {
            "stories": [self._serialize_story(s) for s in story_map.stories],
            "tasks": [self._serialize_task(t) for t in story_map.tasks],
            "total_story_points": story_map.total_story_points,
            "dependency_graph": story_map.dependency_graph,
            "phase_mapping": story_map.phase_mapping,
            "summary": story_map.summary,
        }

    def _serialize_story(self, story: UserStory) -> Dict[str, Any]:
        return {
            "id": story.id,
            "title": story.title,
            "description": story.description,
            "acceptance_criteria": [self._serialize_criterion(c) for c in story.acceptance_criteria],
            "story_points": story.story_points,
            "priority": story.priority,
            "phase_id": story.phase_id,
            "dependencies": story.dependencies,
            "technical_notes": story.technical_notes,
            "risks": story.risks,
            "labels": story.labels,
            "status": story.status,
        }

    def _serialize_criterion(self, criterion: AcceptanceCriterion) -> Dict[str, Any]:
        return {
            "id": criterion.id,
            "description": criterion.description,
            "type": criterion.type,
            "verification": criterion.verification,
        }

    def _serialize_task(self, task: Task) -> Dict[str, Any]:
        return {
            "id": task.id,
            "story_id": task.story_id,
            "title": task.title,
            "description": task.description,
            "estimated_hours": task.estimated_hours,
            "assignee_type": task.assignee_type,
            "dependencies": task.dependencies,
            "status": task.status,
        }
