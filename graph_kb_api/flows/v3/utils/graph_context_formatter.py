"""
Graph context formatting utilities for V3 AskCode workflow.

This module provides functions for formatting graph context packets
into structured text suitable for inclusion in agent prompts.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from graph_kb_api.graph_kb.querying.models import ContextPacket, GraphRAGResult
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


@dataclass
class FormattedGraphContext:
    """Result of formatting graph context packets."""
    formatted_text: str
    packets_included: int
    packets_excluded: int
    total_tokens_used: int
    truncated: bool


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.

    Uses a simple heuristic: ~4 characters per token for English text.
    This is a rough approximation but sufficient for budget enforcement.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Simple heuristic: ~4 characters per token
    # This is conservative and works reasonably well for code and English text
    return len(text) // 4


def format_graph_context(
    graph_context: GraphRAGResult,
    token_budget: int,
    include_relationships: bool = True,
    max_relationships_per_type: int = 5
) -> FormattedGraphContext:
    """
    Format graph context packets for agent prompts.

    Organizes context packets by relationship type and formats them
    with symbol and relationship information in a structured format.
    Token budget is enforced by including highest priority packets first.

    Args:
        graph_context: GraphRAGResult containing context packets
        token_budget: Maximum tokens to use for graph context
        include_relationships: Whether to include relationship details
        max_relationships_per_type: Maximum relationships to show per type

    Returns:
        FormattedGraphContext with formatted text and metadata

    Requirements:
        - 2.2: Format context packets for agent prompts
        - 2.3: Organize by relationship type
        - 6.2: Add symbol and relationship information
    """
    if not graph_context or not graph_context.context_packets:
        logger.debug("No graph context packets to format")
        return FormattedGraphContext(
            formatted_text="",
            packets_included=0,
            packets_excluded=0,
            total_tokens_used=0,
            truncated=False
        )

    logger.info(
        f"Formatting graph context with {len(graph_context.context_packets)} packets, "
        f"token budget: {token_budget}"
    )

    # Sort packets by depth (closer to starting symbols first) and node count (more comprehensive first)
    sorted_packets = _prioritize_packets(graph_context.context_packets)

    # Build formatted sections
    formatted_sections = []
    tokens_used = 0
    packets_included = 0
    packets_excluded = 0
    truncated = False

    # Add header
    header = _format_header(graph_context)
    header_tokens = estimate_tokens(header)

    if header_tokens < token_budget:
        formatted_sections.append(header)
        tokens_used += header_tokens
    else:
        # Budget too small even for header
        logger.warning(f"Token budget ({token_budget}) too small for graph context header")
        return FormattedGraphContext(
            formatted_text="",
            packets_included=0,
            packets_excluded=len(graph_context.context_packets),
            total_tokens_used=0,
            truncated=True
        )

    # Add packets until budget exhausted
    for packet in sorted_packets:
        packet_text = _format_packet(
            packet,
            include_relationships=include_relationships,
            max_relationships_per_type=max_relationships_per_type
        )
        packet_tokens = estimate_tokens(packet_text)

        if tokens_used + packet_tokens <= token_budget:
            formatted_sections.append(packet_text)
            tokens_used += packet_tokens
            packets_included += 1
        else:
            # Budget exhausted
            packets_excluded += 1
            truncated = True
            logger.debug(
                f"Token budget exhausted after {packets_included} packets, "
                f"excluding {packets_excluded} packets"
            )
            break

    # Add footer if packets were excluded
    if truncated:
        footer = _format_footer(packets_excluded)
        footer_tokens = estimate_tokens(footer)

        # Try to fit footer in budget
        if tokens_used + footer_tokens <= token_budget:
            formatted_sections.append(footer)
            tokens_used += footer_tokens

    formatted_text = "\n\n".join(formatted_sections)

    logger.info(
        f"Formatted graph context: {packets_included} packets included, "
        f"{packets_excluded} excluded, {tokens_used} tokens used"
    )

    return FormattedGraphContext(
        formatted_text=formatted_text,
        packets_included=packets_included,
        packets_excluded=packets_excluded,
        total_tokens_used=tokens_used,
        truncated=truncated
    )


def _prioritize_packets(packets: List[ContextPacket]) -> List[ContextPacket]:
    """
    Prioritize context packets for inclusion.

    Packets are sorted by:
    1. Depth (closer to starting symbols first) - lower depth = higher priority
    2. Node count (more comprehensive first) - more nodes = higher priority
    3. Number of relationships (more connected = higher priority)

    This ensures that the most relevant and comprehensive context packets
    are included first when token budget is limited.

    Args:
        packets: List of context packets to prioritize

    Returns:
        Sorted list of packets with highest priority first

    Requirements:
        - 6.4: Sort packets by relevance/depth, include highest priority first
    """
    def priority_key(packet: ContextPacket) -> Tuple[int, int, int]:
        """
        Calculate priority key for sorting.

        Returns tuple of (depth, -node_count, -relationship_count)
        Lower depth is better (closer to starting symbols)
        Higher node_count is better (more comprehensive)
        Higher relationship_count is better (more connected)
        """
        relationship_count = len(packet.relationships_described) if packet.relationships_described else 0

        return (
            packet.depth,              # Lower is better (ascending)
            -packet.node_count,        # Higher is better (descending via negation)
            -relationship_count        # Higher is better (descending via negation)
        )

    sorted_packets = sorted(packets, key=priority_key)

    logger.debug(
        f"Prioritized {len(packets)} packets: "
        f"depth range [{min(p.depth for p in packets)}-{max(p.depth for p in packets)}], "
        f"node count range [{min(p.node_count for p in packets)}-{max(p.node_count for p in packets)}]"
    )

    return sorted_packets


def _format_header(graph_context: GraphRAGResult) -> str:
    """
    Format header section for graph context.

    Args:
        graph_context: GraphRAGResult containing metadata

    Returns:
        Formatted header text
    """
    header_lines = [
        "## Graph Context",
        "",
        f"**Starting Symbols:** {', '.join(graph_context.symbols_found[:10])}",
        f"**Total Nodes Explored:** {graph_context.total_nodes_explored}",
        f"**Context Packets:** {len(graph_context.context_packets)}",
        ""
    ]

    return "\n".join(header_lines)


def _format_packet(
    packet: ContextPacket,
    include_relationships: bool = True,
    max_relationships_per_type: int = 5
) -> str:
    """
    Format a single context packet.

    Args:
        packet: Context packet to format
        include_relationships: Whether to include relationship details
        max_relationships_per_type: Maximum relationships to show per type

    Returns:
        Formatted packet text

    Requirements:
        - 2.2: Include symbol's immediate relationships
        - 2.3: Organize by relationship type
    """
    lines = [
        f"### Symbol: {packet.root_symbol}",
        "",
        f"**Depth:** {packet.depth}",
        f"**Nodes in Context:** {packet.node_count}",
        ""
    ]

    # Add content (the actual code/documentation)
    if packet.content:
        lines.append("**Content:**")
        lines.append("```")
        # Truncate very long content
        content_lines = packet.content.split('\n')
        if len(content_lines) > 20:
            lines.extend(content_lines[:20])
            lines.append(f"... ({len(content_lines) - 20} more lines)")
        else:
            lines.extend(content_lines)
        lines.append("```")
        lines.append("")

    # Add relationships if requested
    if include_relationships and packet.relationships_described:
        lines.append("**Relationships:**")

        # Group relationships by type
        relationships_by_type = _group_relationships(packet.relationships_described)

        for rel_type, targets in relationships_by_type.items():
            if targets:
                # Limit number of relationships shown per type
                shown_targets = targets[:max_relationships_per_type]
                remaining = len(targets) - len(shown_targets)

                targets_str = ", ".join(shown_targets)
                if remaining > 0:
                    targets_str += f" (+{remaining} more)"

                lines.append(f"- **{rel_type}:** {targets_str}")

        lines.append("")

    return "\n".join(lines)


def _group_relationships(relationships: List[str]) -> Dict[str, List[str]]:
    """
    Group relationships by type.

    Relationships are expected to be in format "TYPE:target" or just "target".

    Args:
        relationships: List of relationship strings

    Returns:
        Dictionary mapping relationship type to list of targets

    Requirements:
        - 2.3: Organize relationships by type (CALLS, IMPORTS, CONTAINS, DEFINES)
    """
    grouped: Dict[str, List[str]] = {
        'CALLS': [],
        'IMPORTS': [],
        'CONTAINS': [],
        'DEFINES': [],
        'OTHER': []
    }

    for rel in relationships:
        if ':' in rel:
            # Format: "TYPE:target"
            rel_type, target = rel.split(':', 1)
            rel_type = rel_type.strip().upper()
            target = target.strip()

            if rel_type in grouped:
                grouped[rel_type].append(target)
            else:
                grouped['OTHER'].append(f"{rel_type}:{target}")
        else:
            # No type specified, add to OTHER
            grouped['OTHER'].append(rel.strip())

    # Remove empty groups
    return {k: v for k, v in grouped.items() if v}


def _format_footer(packets_excluded: int) -> str:
    """
    Format footer section when packets are excluded due to token budget.

    Args:
        packets_excluded: Number of packets excluded

    Returns:
        Formatted footer text
    """
    return f"\n*Note: {packets_excluded} additional context packet(s) excluded due to token budget constraints.*"


def enforce_token_budget(
    packets: List[ContextPacket],
    token_budget: int,
    include_relationships: bool = True,
    max_relationships_per_type: int = 5
) -> Tuple[List[ContextPacket], int]:
    """
    Enforce token budget by selecting packets that fit within budget.

    Packets are prioritized by depth and node count. Returns the list
    of packets that fit within the budget and the total tokens used.

    Args:
        packets: List of context packets to filter
        token_budget: Maximum tokens allowed
        include_relationships: Whether to include relationship details
        max_relationships_per_type: Maximum relationships to show per type

    Returns:
        Tuple of (selected packets, total tokens used)

    Requirements:
        - 2.5: Stop adding packets when budget exceeded
        - 6.3: Calculate token usage per packet
    """
    if not packets or token_budget <= 0:
        return [], 0

    # Prioritize packets
    sorted_packets = _prioritize_packets(packets)

    selected_packets = []
    tokens_used = 0

    for packet in sorted_packets:
        # Format packet to get accurate token count
        packet_text = _format_packet(
            packet,
            include_relationships=include_relationships,
            max_relationships_per_type=max_relationships_per_type
        )
        packet_tokens = estimate_tokens(packet_text)

        # Check if packet fits in remaining budget
        if tokens_used + packet_tokens <= token_budget:
            selected_packets.append(packet)
            tokens_used += packet_tokens
        else:
            # Budget exhausted
            logger.debug(
                f"Token budget exhausted: {tokens_used}/{token_budget} tokens used, "
                f"selected {len(selected_packets)}/{len(packets)} packets"
            )
            break

    logger.info(
        f"Token budget enforcement: selected {len(selected_packets)}/{len(packets)} packets, "
        f"using {tokens_used}/{token_budget} tokens"
    )

    return selected_packets, tokens_used


def calculate_packet_tokens(
    packet: ContextPacket,
    include_relationships: bool = True,
    max_relationships_per_type: int = 5
) -> int:
    """
    Calculate token count for a single context packet.

    Args:
        packet: Context packet to calculate tokens for
        include_relationships: Whether to include relationship details
        max_relationships_per_type: Maximum relationships to show per type

    Returns:
        Estimated token count for the packet

    Requirements:
        - 6.3: Calculate token usage per packet
    """
    packet_text = _format_packet(
        packet,
        include_relationships=include_relationships,
        max_relationships_per_type=max_relationships_per_type
    )
    return estimate_tokens(packet_text)


def format_graph_context_for_prompt(
    graph_context: Optional[GraphRAGResult],
    token_budget: int,
    fallback_message: str = ""
) -> str:
    """
    Format graph context for inclusion in agent prompt.

    This is a convenience function that handles None graph_context
    and returns a ready-to-use string for prompt building.

    Args:
        graph_context: GraphRAGResult or None
        token_budget: Maximum tokens to use
        fallback_message: Message to return if no graph context available

    Returns:
        Formatted graph context text or fallback message
    """
    if not graph_context or not graph_context.context_packets:
        return fallback_message

    result = format_graph_context(graph_context, token_budget)
    return result.formatted_text if result.formatted_text else fallback_message
