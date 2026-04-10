"""Property-based tests for PruneAfterResearchNode and PruneAfterOrchestrateNode.

Property 15: Prune Node Safety — validates that prune nodes retain only keys in
the PRESERVE_KEYS allowlist and prune everything else (safe-by-default).

**Validates: Requirements 11.1, 11.2, 11.5**
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.plan_nodes import (
    PRESERVE_AFTER_ORCHESTRATE,
    PRESERVE_AFTER_RESEARCH,
    PruneAfterOrchestrateNode,
    PruneAfterResearchNode,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=50),
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5)
    ),
    max_leaves=10,
)


@st.composite
def research_state_dict(draw: st.DrawFn) -> dict:
    """Generate a research sub-dict with arbitrary keys plus optional preserved keys."""
    extra = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=30).filter(
                lambda k: k not in PRESERVE_AFTER_RESEARCH
            ),
            json_values,
            max_size=10,
        )
    )
    for key in PRESERVE_AFTER_RESEARCH:
        if draw(st.booleans()):
            extra[key] = draw(json_values)
    return extra


@st.composite
def orchestrate_state_dict(draw: st.DrawFn) -> dict:
    """Generate an orchestrate sub-dict with arbitrary keys plus optional preserved keys."""
    extra = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=30).filter(
                lambda k: k not in PRESERVE_AFTER_ORCHESTRATE
            ),
            json_values,
            max_size=10,
        )
    )
    for key in PRESERVE_AFTER_ORCHESTRATE:
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
# Property 15.1: Prune research retains only preserved keys
# ---------------------------------------------------------------------------


class TestPruneResearchRetainsOnlyPreservedKeys:
    """For any research state dict, after pruning, only keys in
    PRESERVE_AFTER_RESEARCH survive with their original values.

    Feature: plan-feature-refactoring, Property 15: Prune Node Safety
    **Validates: Requirements 11.1, 11.2, 11.5**
    """

    @given(research=research_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_preserved_keys_retained(self, research: dict):
        node = PruneAfterResearchNode()
        state = {"research": research}
        result = await node._execute_step(state, {})
        pruned = result.output["research"]

        for key, value in research.items():
            if key in PRESERVE_AFTER_RESEARCH:
                assert key in pruned, f"Preserved key '{key}' was removed"
                assert pruned[key] == value, (
                    f"Value for preserved key '{key}' changed: "
                    f"{value!r} -> {pruned[key]!r}"
                )


# ---------------------------------------------------------------------------
# Property 15.2: Prune research removes non-preserved keys
# ---------------------------------------------------------------------------


class TestPruneResearchRemovesNonPreservedKeys:
    """For any research state dict containing keys outside PRESERVE_AFTER_RESEARCH,
    after pruning, those keys are absent.

    Feature: plan-feature-refactoring, Property 15: Prune Node Safety
    **Validates: Requirements 11.1, 11.2, 11.5**
    """

    @given(research=research_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_non_preserved_keys_removed(self, research: dict):
        node = PruneAfterResearchNode()
        state = {"research": research}
        result = await node._execute_step(state, {})
        pruned = result.output["research"]

        for key in pruned:
            assert key in PRESERVE_AFTER_RESEARCH, (
                f"Non-preserved key '{key}' survived pruning"
            )


# ---------------------------------------------------------------------------
# Property 15.3: Prune orchestrate retains only preserved keys
# ---------------------------------------------------------------------------


class TestPruneOrchestrateRetainsOnlyPreservedKeys:
    """Same as 15.1 but for orchestrate state and PRESERVE_AFTER_ORCHESTRATE.

    Feature: plan-feature-refactoring, Property 15: Prune Node Safety
    **Validates: Requirements 11.1, 11.2, 11.5**
    """

    @given(orchestrate=orchestrate_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_preserved_keys_retained(self, orchestrate: dict):
        node = PruneAfterOrchestrateNode()
        state = {"orchestrate": orchestrate}
        result = await node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        for key, value in orchestrate.items():
            if key in PRESERVE_AFTER_ORCHESTRATE:
                assert key in pruned, f"Preserved key '{key}' was removed"
                assert pruned[key] == value, (
                    f"Value for preserved key '{key}' changed: "
                    f"{value!r} -> {pruned[key]!r}"
                )


# ---------------------------------------------------------------------------
# Property 15.4: Prune orchestrate removes non-preserved keys
# ---------------------------------------------------------------------------


class TestPruneOrchestrateRemovesNonPreservedKeys:
    """Same as 15.2 but for orchestrate.

    Feature: plan-feature-refactoring, Property 15: Prune Node Safety
    **Validates: Requirements 11.1, 11.2, 11.5**
    """

    @given(orchestrate=orchestrate_state_dict())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_non_preserved_keys_removed(self, orchestrate: dict):
        node = PruneAfterOrchestrateNode()
        state = {"orchestrate": orchestrate}
        result = await node._execute_step(state, {})
        pruned = result.output["orchestrate"]

        for key in pruned:
            assert key in PRESERVE_AFTER_ORCHESTRATE, (
                f"Non-preserved key '{key}' survived pruning"
            )


# ---------------------------------------------------------------------------
# Property 15.5: Prune nodes never modify artifacts
# ---------------------------------------------------------------------------


class TestPruneNodesNeverModifyArtifacts:
    """For any state with artifacts dict, the prune node output does not contain
    an "artifacts" key.

    Feature: plan-feature-refactoring, Property 15: Prune Node Safety
    **Validates: Requirements 11.1, 11.5**
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
