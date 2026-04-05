"""Property-based tests for PruneAfterResearchNode and PruneAfterOrchestrateNode.

Property 15: Prune Node Safety — validates that prune nodes preserve non-pruned
keys, remove target keys, and never modify artifacts.

**Validates: Requirements 18.1, 18.2, 18.3**
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.plan_nodes import (
    PruneAfterOrchestrateNode,
    PruneAfterResearchNode,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary JSON-like values for dict entries
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=50),
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5)
    ),
    max_leaves=10,
)

RESEARCH_PRUNE_KEYS = {"web_results", "vector_results", "graph_results"}
ORCHESTRATE_PRUNE_KEYS = {"critique_history", "iteration_count", "current_task_context"}


@st.composite
def research_state_dict(draw: st.DrawFn) -> dict:
    """Generate a research sub-dict with arbitrary keys plus optional prune targets."""
    # Always include some arbitrary non-pruned keys
    extra = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=30).filter(
                lambda k: k not in RESEARCH_PRUNE_KEYS
            ),
            json_values,
            max_size=10,
        )
    )
    # Optionally include prune-target keys
    for key in RESEARCH_PRUNE_KEYS:
        if draw(st.booleans()):
            extra[key] = draw(json_values)
    return extra


@st.composite
def orchestrate_state_dict(draw: st.DrawFn) -> dict:
    """Generate an orchestrate sub-dict with arbitrary keys plus optional prune targets."""
    extra = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=30).filter(
                lambda k: k not in ORCHESTRATE_PRUNE_KEYS
            ),
            json_values,
            max_size=10,
        )
    )
    for key in ORCHESTRATE_PRUNE_KEYS:
        if draw(st.booleans()):
            extra[key] = draw(json_values)
    return extra


@st.composite
def artifacts_dict(draw: st.DrawFn) -> dict:
    """Generate an artifacts dict mimicking ArtifactRef entries."""
    return draw(
        st.dictionaries(
            st.text(min_size=1, max_size=40),
            st.fixed_dictionaries(
                {
                    "key": st.text(min_size=1, max_size=60),
                    "content_hash": st.text(min_size=64, max_size=64),
                    "size_bytes": st.integers(min_value=0, max_value=1_000_000),
                }
            ),
            max_size=5,
        )
    )


# ---------------------------------------------------------------------------
# Property 15.1: Prune research preserves non-pruned keys
# ---------------------------------------------------------------------------


class TestPruneResearchPreservesNonPrunedKeys:
    """For any research state dict with arbitrary keys, after pruning, all keys
    NOT in {web_results, vector_results, graph_results} are preserved with
    identical values.

    **Validates: Requirements 18.1, 18.2, 18.3**
    """

    @given(research=research_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_non_pruned_keys_preserved(self, research: dict):
        node = PruneAfterResearchNode()
        state = {"research": research}
        result = await node._execute_step(state, {})
        pruned = result.output["research"]

        for key, value in research.items():
            if key not in RESEARCH_PRUNE_KEYS:
                assert key in pruned, f"Non-pruned key '{key}' was removed"
                assert pruned[key] == value, (
                    f"Value for non-pruned key '{key}' changed: "
                    f"{value!r} -> {pruned[key]!r}"
                )


# ---------------------------------------------------------------------------
# Property 15.2: Prune research removes target keys
# ---------------------------------------------------------------------------


class TestPruneResearchRemovesTargetKeys:
    """For any research state dict containing web_results/vector_results/graph_results,
    after pruning, those keys are absent.

    **Validates: Requirements 18.1, 18.2, 18.3**
    """

    @given(research=research_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_target_keys_removed(self, research: dict):
        node = PruneAfterResearchNode()
        state = {"research": research}
        result = await node._execute_step(state, {})
        pruned = result.output["research"]

        for key in RESEARCH_PRUNE_KEYS:
            assert key not in pruned, f"Prune target key '{key}' was not removed"


# ---------------------------------------------------------------------------
# Property 15.3: Prune orchestrate preserves non-pruned keys
# ---------------------------------------------------------------------------


class TestPruneOrchestratePreservesNonPrunedKeys:
    """Same as 15.1 but for orchestrate state and
    {critique_history, iteration_count, current_task_context}.

    **Validates: Requirements 18.1, 18.2, 18.3**
    """

    @given(orchestrate=orchestrate_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_non_pruned_keys_preserved(self, orchestrate: dict):
        node = PruneAfterOrchestrateNode()
        state = {"orchestrate": orchestrate}
        result = await node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        for key, value in orchestrate.items():
            if key not in ORCHESTRATE_PRUNE_KEYS:
                assert key in pruned, f"Non-pruned key '{key}' was removed"
                assert pruned[key] == value, (
                    f"Value for non-pruned key '{key}' changed: "
                    f"{value!r} -> {pruned[key]!r}"
                )


# ---------------------------------------------------------------------------
# Property 15.4: Prune orchestrate removes target keys
# ---------------------------------------------------------------------------


class TestPruneOrchestrateRemovesTargetKeys:
    """Same as 15.2 but for orchestrate.

    **Validates: Requirements 18.1, 18.2, 18.3**
    """

    @given(orchestrate=orchestrate_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_target_keys_removed(self, orchestrate: dict):
        node = PruneAfterOrchestrateNode()
        state = {"orchestrate": orchestrate}
        result = await node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        for key in ORCHESTRATE_PRUNE_KEYS:
            assert key not in pruned, f"Prune target key '{key}' was not removed"


# ---------------------------------------------------------------------------
# Property 15.5: Prune nodes never modify artifacts
# ---------------------------------------------------------------------------


class TestPruneNodesNeverModifyArtifacts:
    """For any state with artifacts dict, the prune node output does not contain
    an "artifacts" key (artifacts are at top-level state, not inside the pruned
    sub-dict).

    **Validates: Requirements 18.1, 18.2, 18.3**
    """

    @given(
        research=research_state_dict(),
        artifacts=artifacts_dict(),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_research_prune_does_not_touch_artifacts(
        self, research: dict, artifacts: dict
    ):
        node = PruneAfterResearchNode()
        state = {"research": research, "artifacts": artifacts}
        result = await node._execute_step(state, {})
        assert "artifacts" not in result.output, (
            "PruneAfterResearchNode output must not contain 'artifacts' key"
        )

    @given(
        orchestrate=orchestrate_state_dict(),
        artifacts=artifacts_dict(),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_orchestrate_prune_does_not_touch_artifacts(
        self, orchestrate: dict, artifacts: dict
    ):
        node = PruneAfterOrchestrateNode()
        state = {"orchestrate": orchestrate, "artifacts": artifacts}
        result = await node._execute_step(state, {})
        assert "artifacts" not in result.output, (
            "PruneAfterOrchestrateNode output must not contain 'artifacts' key"
        )
