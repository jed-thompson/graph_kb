"""Property-based tests for ToolPlannerAgent.

Property 10: Agent-tool consistency — Every assigned tool is a member of the
agent's required_tools or optional_tools set.

**Validates: Requirements 22.1, 22.2**
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.agents.tool_planner_agent import ToolPlannerAgent

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Known context-requirement keywords that can trigger optional tool selection
_KNOWN_KEYWORDS = [
    "architecture",
    "hotspot",
    "entry_point",
    "symbol_ref",
    "references",
    "related_files",
    "file_snippet",
    "symbol_details",
    "architecture_overview",
    "symbol:UserService",
    "doc:api_spec.yaml",
]

# Agent types that have tools assigned (tool_planner has no tools)
_AGENT_TYPES_WITH_TOOLS = [
    "architect",
    "lead_engineer",
    "doc_extractor",
    "reviewer_critic",
]


@st.composite
def agent_type_and_context(draw: st.DrawFn):
    """Generate a random agent type and context requirements.

    Mixes known keywords (which may trigger optional tools) with random
    strings (which should not cause tools outside the capability set).
    """
    agent_type = draw(st.sampled_from(_AGENT_TYPES_WITH_TOOLS))

    known = draw(st.lists(st.sampled_from(_KNOWN_KEYWORDS), max_size=6, unique=True))
    random_strings = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
                min_size=0,
                max_size=30,
            ),
            max_size=4,
        )
    )
    context_requirements = draw(st.permutations(known + random_strings))

    return agent_type, context_requirements


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestAgentToolConsistency:
    """Property 10: Agent-tool consistency.

    Every assigned tool is a member of the agent's required_tools ∪
    optional_tools set.

    Formally: ∀agent, ∀tool ∈ agent.assigned_tools:
              tool ∈ agent.capability.required_tools ∪ agent.capability.optional_tools

    **Validates: Requirements 22.1, 22.2**
    """

    # ---- _determine_tools (instance method) ----

    @given(data=agent_type_and_context())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_determine_tools_returns_only_allowed_tools(self, data):
        """_determine_tools never returns a tool outside the capability set."""
        agent_type, context_requirements = data

        planner = ToolPlannerAgent()
        agent_cap = ToolPlannerAgent._get_agent_capability(agent_type)
        allowed = set(agent_cap.required_tools) | set(agent_cap.optional_tools)

        tools = planner._determine_tools(agent_cap, context_requirements)

        for tool in tools:
            assert tool in allowed, (
                f"Tool {tool!r} assigned to {agent_type} is not in "
                f"required_tools ∪ optional_tools. Allowed: {allowed}"
            )

    @given(data=agent_type_and_context())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_determine_tools_always_includes_required(self, data):
        """_determine_tools always includes every required tool."""
        agent_type, context_requirements = data

        planner = ToolPlannerAgent()
        agent_cap = ToolPlannerAgent._get_agent_capability(agent_type)
        tools = planner._determine_tools(agent_cap, context_requirements)

        for rt in agent_cap.required_tools:
            assert rt in tools, (
                f"Required tool {rt!r} missing from assignment for {agent_type}"
            )

    # ---- execute() (full agent method) ----

    @given(data=agent_type_and_context())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_execute_assigns_only_allowed_tools(self, data):
        """ToolPlannerAgent.execute() never assigns a tool outside capability."""
        agent_type, context_requirements = data

        agent = ToolPlannerAgent()
        task = {
            "task_id": "prop_task",
            "agent_type": agent_type,
            "context_requirements": context_requirements,
        }
        state = {"todo_list": [task]}
        result = await agent.execute(task, state, workflow_context=None)

        agent_cap = ToolPlannerAgent._get_agent_capability(agent_type)
        allowed = set(agent_cap.required_tools) | set(agent_cap.optional_tools)

        tools = result["task_tool_assignments"]["prop_task"]
        for tool in tools:
            assert tool in allowed, (
                f"Tool {tool!r} assigned via execute() to {agent_type} "
                f"is not in required_tools ∪ optional_tools. Allowed: {allowed}"
            )

    # ---- replan() ----

    @given(data=agent_type_and_context())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_replan_assigns_only_allowed_tools(self, data):
        """ToolPlannerAgent.replan() never assigns a tool outside capability."""
        agent_type, context_requirements = data

        agent = ToolPlannerAgent()
        task = {
            "task_id": "prop_replan",
            "agent_type": agent_type,
            "context_requirements": context_requirements,
        }
        # Use half the context as rework feedback, half as clarification
        mid = len(context_requirements) // 2
        rework_feedback = " ".join(context_requirements[:mid])
        clarification = {
            f"gap_{i}": req for i, req in enumerate(context_requirements[mid:])
        }
        state = {"clarification_responses": clarification}

        result = await agent.replan(task, rework_feedback=rework_feedback, state=state)

        agent_cap = ToolPlannerAgent._get_agent_capability(agent_type)
        allowed = set(agent_cap.required_tools) | set(agent_cap.optional_tools)

        for tool in result["tool_assignments"]:
            assert tool in allowed, (
                f"Tool {tool!r} assigned via replan() to {agent_type} "
                f"is not in required_tools ∪ optional_tools. Allowed: {allowed}"
            )
