"""Property-based tests for ContextSummarizerNode.

Property 12: Context summarization — For any completed section, the summary
is shorter than the original and preserves key entities.

**Validates: Requirements 6.1**
"""

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.context_summarizer_node import (
    _MIN_LENGTH_FOR_SUMMARIZATION,
    ContextSummarizerNode,
    summarize_text,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Key technical terms that should be preserved in summaries
_TECHNICAL_TERMS = [
    "interface",
    "class",
    "def",
    "model",
    "constraint",
    "endpoint",
    "schema",
    "api",
    "type",
    "return",
    "param",
    "require",
    "validate",
    "error",
    "response",
    "request",
]


@st.composite
def section_draft_with_entities(draw: st.DrawFn):
    """Generate a section draft that contains some key technical entities.

    The draft is long enough to trigger summarisation (> _MIN_LENGTH_FOR_SUMMARIZATION)
    and contains a mix of filler prose and sentences with key patterns.
    """
    # Generate several filler sentences
    n_filler = draw(st.integers(min_value=4, max_value=20))
    filler_sentences = [
        draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "Zs"), whitelist_characters=",."
                ),
                min_size=20,
                max_size=80,
            )
        )
        + "."
        for _ in range(n_filler)
    ]

    # Generate sentences containing key technical terms
    n_key = draw(st.integers(min_value=1, max_value=6))
    key_sentences = []
    chosen_terms = draw(
        st.lists(
            st.sampled_from(_TECHNICAL_TERMS),
            min_size=n_key,
            max_size=n_key,
        )
    )
    for term in chosen_terms:
        prefix = draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "Zs"), whitelist_characters=","
                ),
                min_size=5,
                max_size=30,
            )
        )
        key_sentences.append(f"{prefix} {term} {prefix}.")

    # Interleave: put some filler first, then key sentences, then more filler
    mid = len(filler_sentences) // 2
    all_sentences = filler_sentences[:mid] + key_sentences + filler_sentences[mid:]
    draft = " ".join(all_sentences)

    # Ensure the draft is long enough
    assume(len(draft) >= _MIN_LENGTH_FOR_SUMMARIZATION)

    return draft, chosen_terms


@st.composite
def long_section_draft(draw: st.DrawFn):
    """Generate a long section draft (no guaranteed key entities)."""
    n_sentences = draw(st.integers(min_value=10, max_value=30))
    sentences = [
        draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "Zs"), whitelist_characters=",."
                ),
                min_size=30,
                max_size=120,
            )
        )
        + "."
        for _ in range(n_sentences)
    ]
    draft = " ".join(sentences)
    assume(len(draft) >= _MIN_LENGTH_FOR_SUMMARIZATION)
    return draft


@st.composite
def node_state(draw: st.DrawFn):
    """Generate a valid state dict for the ContextSummarizerNode."""
    draft, terms = draw(section_draft_with_entities())
    section_id = draw(st.from_regex(r"[a-z][a-z0-9_]{1,15}", fullmatch=True))

    # Optionally include some existing summaries
    n_existing = draw(st.integers(min_value=0, max_value=3))
    existing_summaries = {}
    for i in range(n_existing):
        sid = f"prev_section_{i}"
        existing_summaries[sid] = f"Summary of {sid}."

    state = {
        "agent_draft": draft,
        "current_task": {"section_id": section_id},
        "section_summaries": existing_summaries,
    }
    return state, terms, section_id


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestContextSummarization:
    """Property 12: Context summarization — summary is shorter than original
    and preserves key entities.

    For any completed section, the summary produced by ContextSummarizerNode
    is shorter than the original draft and preserves key technical entities
    (interfaces, data models, constraints, etc.) that appear in the original.

    **Validates: Requirements 6.1**
    """

    @given(data=section_draft_with_entities())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_shorter_than_original(self, data):
        """The summary must be shorter than or equal to the original for
        non-trivial inputs."""
        draft, _ = data
        summary = summarize_text(draft)
        assert len(summary) <= len(draft), (
            f"Summary ({len(summary)} chars) should not be longer than "
            f"original ({len(draft)} chars)"
        )

    @given(data=section_draft_with_entities())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_key_entities_preserved(self, data):
        """Key technical entities present in the original should appear in
        the summary."""
        draft, chosen_terms = data
        summary = summarize_text(draft)

        # For each key term that appears in the original, check it's in the summary
        for term in chosen_terms:
            # Verify the term is actually in the draft (it should be by construction)
            if term.lower() in draft.lower():
                assert term.lower() in summary.lower(), (
                    f"Key entity '{term}' present in original but missing from summary.\n"
                    f"Original length: {len(draft)}, Summary length: {len(summary)}"
                )

    @given(state_data=node_state())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_node_produces_valid_state_updates(self, state_data):
        """The node must return section_summaries and summarized_context."""
        state, terms, section_id = state_data
        node = ContextSummarizerNode()
        result = await node(state)

        assert "section_summaries" in result
        assert "summarized_context" in result
        assert section_id in result["section_summaries"]

        # The summary stored for this section should be shorter than the draft
        stored_summary = result["section_summaries"][section_id]
        original = state["agent_draft"]
        assert len(stored_summary) <= len(original)

    @given(draft=long_section_draft())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_respects_max_ratio(self, draft):
        """For long texts, the summary should be at most 50% of the original."""
        summary = summarize_text(draft)
        max_allowed = int(len(draft) * 0.50)
        assert len(summary) <= max_allowed, (
            f"Summary ({len(summary)} chars) exceeds 50% of original "
            f"({len(draft)} chars, max {max_allowed})"
        )
