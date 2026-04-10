"""Property-based tests for selective artifact hydration.

Tests the FetchContextNode._compute_needed_artifact_keys() static method that
determines which artifacts to hydrate based on task metadata.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes import FetchContextNode

# --- Known context_requirements that map to artifact prefixes ---

_KNOWN_CONTEXT_REQS = list(FetchContextNode._CONTEXT_REQ_TO_ARTIFACT_PREFIXES.keys())

# --- Strategies ---

# Artifact key prefixes that mirror real artifact naming conventions
_ARTIFACT_KEY_PREFIXES = st.sampled_from([
    "research.", "context.", "plan.", "planning.", "assembly.",
    "orchestrate.", "misc.",
])

_KEY_SUFFIX = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_."),
    min_size=1,
    max_size=20,
)

_ARTIFACT_KEY = st.builds(lambda prefix, suffix: f"{prefix}{suffix}", _ARTIFACT_KEY_PREFIXES, _KEY_SUFFIX)

_AVAILABLE_KEYS = st.frozensets(_ARTIFACT_KEY, min_size=0, max_size=20).map(set)

_RELEVANT_DOC = st.fixed_dictionaries({
    "doc_id": st.text(min_size=1, max_size=20),
    "sections": st.lists(st.text(min_size=1, max_size=30), max_size=5),
})

_RELEVANT_DOCS = st.lists(_RELEVANT_DOC, min_size=0, max_size=5)

_CONTEXT_REQUIREMENTS = st.lists(
    st.sampled_from(_KNOWN_CONTEXT_REQS + ["unknown_req", "other"]),
    min_size=0,
    max_size=6,
)


class TestSelectiveArtifactHydrationProperty:
    """Feature: plan-feature-refactoring, Property 15: Selective artifact hydration loads only needed artifacts

    **Validates: Requirements 19.1**
    """

    @given(
        relevant_docs=_RELEVANT_DOCS,
        context_requirements=_CONTEXT_REQUIREMENTS,
        available_keys=_AVAILABLE_KEYS,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_needed_keys_subset_of_available(
        self,
        relevant_docs: list[dict],
        context_requirements: list[str],
        available_keys: set[str],
    ):
        """The computed needed set is always a subset of available keys.

        Feature: plan-feature-refactoring, Property 15: Selective artifact hydration loads only needed artifacts

        **Validates: Requirements 19.1**
        """
        needed = FetchContextNode._compute_needed_artifact_keys(
            relevant_docs, context_requirements, available_keys,
        )
        assert needed.issubset(available_keys), (
            f"needed keys {needed - available_keys} not in available_keys"
        )

    @given(
        relevant_docs=_RELEVANT_DOCS,
        context_requirements=_CONTEXT_REQUIREMENTS,
        available_keys=_AVAILABLE_KEYS,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_needed_keys_size_at_most_available(
        self,
        relevant_docs: list[dict],
        context_requirements: list[str],
        available_keys: set[str],
    ):
        """The number of needed keys is at most the total artifact count.

        Feature: plan-feature-refactoring, Property 15: Selective artifact hydration loads only needed artifacts

        **Validates: Requirements 19.1**
        """
        needed = FetchContextNode._compute_needed_artifact_keys(
            relevant_docs, context_requirements, available_keys,
        )
        assert len(needed) <= len(available_keys)

    @given(
        relevant_docs=st.lists(_RELEVANT_DOC, min_size=1, max_size=5),
        context_requirements=_CONTEXT_REQUIREMENTS,
        available_keys=_AVAILABLE_KEYS,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_relevant_docs_includes_all_context_keys(
        self,
        relevant_docs: list[dict],
        context_requirements: list[str],
        available_keys: set[str],
    ):
        """When relevant_docs is non-empty, all context.* keys are included.

        Feature: plan-feature-refactoring, Property 15: Selective artifact hydration loads only needed artifacts

        **Validates: Requirements 19.1**
        """
        needed = FetchContextNode._compute_needed_artifact_keys(
            relevant_docs, context_requirements, available_keys,
        )
        context_keys = {k for k in available_keys if k.startswith("context.")}
        assert context_keys.issubset(needed), (
            f"context keys {context_keys - needed} missing from needed set"
        )

    @given(
        context_requirements=st.lists(st.sampled_from(_KNOWN_CONTEXT_REQS), min_size=1, max_size=6),
        available_keys=_AVAILABLE_KEYS,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_needed_keys_match_expected_prefixes(
        self,
        context_requirements: list[str],
        available_keys: set[str],
    ):
        """Each needed key matches at least one prefix from the context_requirements mapping.

        Feature: plan-feature-refactoring, Property 15: Selective artifact hydration loads only needed artifacts

        **Validates: Requirements 19.1**
        """
        needed = FetchContextNode._compute_needed_artifact_keys(
            relevant_docs=[],
            context_requirements=context_requirements,
            available_keys=available_keys,
        )
        # Collect all expected prefixes from the given requirements
        expected_prefixes: list[str] = []
        for req in context_requirements:
            prefixes = FetchContextNode._CONTEXT_REQ_TO_ARTIFACT_PREFIXES.get(req, [])
            expected_prefixes.extend(prefixes)

        for key in needed:
            assert any(
                key == prefix or key.startswith(prefix)
                for prefix in expected_prefixes
            ), f"key {key!r} does not match any expected prefix {expected_prefixes}"

    @given(available_keys=_AVAILABLE_KEYS)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_inputs_return_empty(self, available_keys: set[str]):
        """When both relevant_docs and context_requirements are empty, no keys are needed.

        Feature: plan-feature-refactoring, Property 15: Selective artifact hydration loads only needed artifacts

        **Validates: Requirements 19.1**
        """
        needed = FetchContextNode._compute_needed_artifact_keys(
            relevant_docs=[],
            context_requirements=[],
            available_keys=available_keys,
        )
        assert needed == set()
