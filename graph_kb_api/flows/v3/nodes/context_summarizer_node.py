"""
Context summarizer node for the feature spec workflow.

Compresses full section drafts into key-point summaries preserving
interfaces, data models, and constraints. Maintains a ``section_summaries``
dict (section_id -> condensed summary) using ``operator.or_`` and produces
a ``summarized_context`` string for downstream nodes (e.g. the reviewer).

The summarizer uses a simple extractive approach (no LLM required):
  1. Split the draft into sentences.
  2. Keep sentences that contain key technical patterns (interface, class,
     def, model, constraint, endpoint, schema, etc.).
  3. Always include the first few sentences for context.
  4. Ensure the summary is at most 50% of the original length for long texts.
"""

import re
from typing import Any, Dict, List

from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3

# Patterns that indicate key technical content worth preserving
_KEY_PATTERNS: List[re.Pattern] = [
    re.compile(r"\binterface\b", re.IGNORECASE),
    re.compile(r"\bclass\b", re.IGNORECASE),
    re.compile(r"\bdef\b", re.IGNORECASE),
    re.compile(r"\bmodel\b", re.IGNORECASE),
    re.compile(r"\bconstraint\b", re.IGNORECASE),
    re.compile(r"\bendpoint\b", re.IGNORECASE),
    re.compile(r"\bschema\b", re.IGNORECASE),
    re.compile(r"\bapi\b", re.IGNORECASE),
    re.compile(r"\btype\b", re.IGNORECASE),
    re.compile(r"\breturn\b", re.IGNORECASE),
    re.compile(r"\bparam\b", re.IGNORECASE),
    re.compile(r"\brequire", re.IGNORECASE),
    re.compile(r"\bvalidat", re.IGNORECASE),
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bresponse\b", re.IGNORECASE),
    re.compile(r"\brequest\b", re.IGNORECASE),
]

# Minimum length (in characters) below which we return the text as-is
_MIN_LENGTH_FOR_SUMMARIZATION = 100

# Maximum ratio of summary length to original length for long texts
_MAX_RATIO = 0.50

# Number of leading sentences always included for context
_LEADING_SENTENCES = 2

# Regex to split text into sentences (handles common abbreviations poorly,
# but good enough for extractive summarisation of technical prose).
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\n+|\n(?=[-*#])")


def _split_sentences(text: str) -> List[str]:
    """Split *text* into sentence-like chunks."""
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _has_key_pattern(sentence: str) -> bool:
    """Return True if *sentence* contains at least one key technical pattern."""
    return any(pat.search(sentence) for pat in _KEY_PATTERNS)


def summarize_text(text: str) -> str:
    """Produce an extractive summary of *text*.

    For short texts (< ``_MIN_LENGTH_FOR_SUMMARIZATION`` chars) the original
    text is returned unchanged.

    For longer texts the algorithm:
      1. Always keeps the first ``_LEADING_SENTENCES`` sentences.
      2. Keeps any subsequent sentence that matches a key technical pattern.
      3. Trims the result so it is at most ``_MAX_RATIO`` of the original
         length (by character count).

    Returns the summarised string.
    """
    if not text or len(text) < _MIN_LENGTH_FOR_SUMMARIZATION:
        return text

    sentences = _split_sentences(text)
    if not sentences:
        return text

    # Classify sentences: leading, key-pattern, or filler
    leading: List[int] = list(range(min(_LEADING_SENTENCES, len(sentences))))
    key_indices: List[int] = [i for i in range(len(sentences)) if i not in leading and _has_key_pattern(sentences[i])]
    filler_indices: List[int] = [i for i in range(len(sentences)) if i not in leading and i not in key_indices]

    # Build kept list: leading + key + filler (in original order)
    kept_indices = sorted(set(leading + key_indices + filler_indices))
    kept = [sentences[i] for i in kept_indices]
    summary = " ".join(kept)

    max_len = int(len(text) * _MAX_RATIO)

    # If over budget, drop filler sentences first (from the end)
    filler_set = set(filler_indices)
    removable = [i for i in reversed(kept_indices) if i in filler_set]
    kept_set = set(kept_indices)
    for idx in removable:
        if len(summary) <= max_len:
            break
        kept_set.discard(idx)
        kept = [sentences[i] for i in sorted(kept_set)]
        summary = " ".join(kept)

    # If still over budget, drop leading sentences (except the very first)
    if len(summary) > max_len:
        for idx in reversed(leading[1:]):
            if len(summary) <= max_len:
                break
            kept_set.discard(idx)
            kept = [sentences[i] for i in sorted(kept_set)]
            summary = " ".join(kept)

    return summary


class ContextSummarizerNode(BaseWorkflowNodeV3):
    """Summarizes completed section context to prevent context window bloat.

    After a producing agent (Architect, LeadEngineer, DocExtractor) creates
    a draft, this node:
      1. Takes the current ``agent_draft`` from state.
      2. Produces a condensed summary (shorter than the original for
         non-trivial inputs).
      3. Stores it in ``section_summaries[section_id]``.
      4. Produces a ``summarized_context`` string combining relevant
         summaries for the reviewer.
    """

    def __init__(self) -> None:
        super().__init__("context_summarizer")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        self.logger.info("ContextSummarizerNode: summarizing current draft")

        agent_draft: str = state.get("agent_draft", "") or ""
        current_task: Dict[str, Any] = state.get("current_task", {}) or {}
        section_id: str = current_task.get("section_id", "unknown")
        existing_summaries: Dict[str, str] = dict(state.get("section_summaries", {}) or {})

        # Summarize the current draft
        summary = summarize_text(agent_draft)

        # Update section_summaries (will be merged via operator.or_)
        new_summaries = {section_id: summary}

        # Build summarized_context for the reviewer by combining all
        # available summaries (existing + new)
        combined = {**existing_summaries, **new_summaries}
        context_parts: List[str] = []
        for sid, s in sorted(combined.items()):
            context_parts.append(f"[{sid}] {s}")

        summarized_context = "\n\n".join(context_parts)

        self.logger.info(
            f"ContextSummarizerNode: summarized section '{section_id}' ({len(agent_draft)} -> {len(summary)} chars)"
        )

        return NodeExecutionResult.success(
            output={
                "section_summaries": new_summaries,
                "summarized_context": summarized_context,
            }
        )
