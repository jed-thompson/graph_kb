"""
Token estimation utilities for v3 workflows.

This module provides accurate token counting for LLM messages,
including tool calls and tool results, using tiktoken for proper tokenization.
"""

from typing import Any, List

import tiktoken

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class TokenEstimator:
    """Estimates token usage for LLM messages with tool calls."""

    def __init__(self, encoding_name: str = "cl100k_base"):
        """
        Initialize token estimator.

        Args:
            encoding_name: Tiktoken encoding to use (default: cl100k_base for GPT-4/GPT-3.5)
        """
        try:
            self._tokenizer = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.warning(f"Failed to load tiktoken encoding {encoding_name}: {e}, falling back to word count")
            self._tokenizer = None

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        if not text:
            return 0

        if self._tokenizer:
            try:
                return len(self._tokenizer.encode(text))
            except Exception as e:
                logger.warning(f"Tiktoken encoding failed: {e}, falling back to word count")

        # Fallback to word-based estimation
        return int(len(str(text).split()) * 1.33)

    def estimate_message_tokens(self, message: Any) -> int:
        """
        Estimate tokens for a single message, including tool calls and results.

        Args:
            message: LangChain message object (HumanMessage, AIMessage, ToolMessage, etc.)

        Returns:
            Estimated token count
        """
        total_tokens = 0

        # Count message content
        if hasattr(message, 'content') and message.content:
            content_str = str(message.content)
            total_tokens += self.count_tokens(content_str)

        # Count tool calls (if present in AIMessage)
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tool_call in message.tool_calls:
                # Tool name
                tool_name = tool_call.get('name', '')
                total_tokens += self.count_tokens(tool_name)

                # Tool arguments (JSON)
                tool_args = tool_call.get('args', {})
                args_str = str(tool_args)
                total_tokens += self.count_tokens(args_str)

                # Add overhead for tool call structure (~10 tokens)
                total_tokens += 10

        # Count tool results (if this is a ToolMessage)
        if hasattr(message, 'name'):
            # This is likely a tool result message
            tool_name = message.name
            total_tokens += self.count_tokens(tool_name)

            # Tool result content already counted above in message.content
            # Add overhead for tool result structure (~5 tokens)
            total_tokens += 5

        # Add per-message overhead (~4 tokens for message structure)
        total_tokens += 4

        return total_tokens

    def estimate_messages_tokens(self, messages: List[Any]) -> int:
        """
        Estimate total tokens for a list of messages.

        Args:
            messages: List of LangChain message objects

        Returns:
            Total estimated token count
        """
        if not messages:
            return 0

        total_tokens = 0
        for message in messages:
            total_tokens += self.estimate_message_tokens(message)

        return total_tokens

    def truncate_to_tokens(
        self,
        text: str,
        max_tokens: int,
        suffix: str = "\n... [truncated]",
    ) -> str:
        """
        Truncate text to fit within max_tokens, adding suffix if truncated.

        Args:
            text: The text to potentially truncate
            max_tokens: Maximum number of tokens allowed
            suffix: String to append if truncation occurs (not counted toward limit)

        Returns:
            Original text if within limit, otherwise truncated text with suffix
        """
        if not text:
            return text

        if not self._tokenizer:
            # Fallback to character-based truncation (rough estimate: 4 chars per token)
            char_limit = max_tokens * 4
            if len(text) <= char_limit:
                return text
            return text[: char_limit - len(suffix)] + suffix

        tokens = self._tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return text

        # Reserve space for suffix tokens
        suffix_tokens = len(self._tokenizer.encode(suffix))
        truncated_tokens = tokens[: max_tokens - suffix_tokens]
        return self._tokenizer.decode(truncated_tokens) + suffix


# Global singleton instance
_token_estimator: TokenEstimator = None


def get_token_estimator() -> TokenEstimator:
    """
    Get the global token estimator instance.

    Returns:
        TokenEstimator singleton
    """
    global _token_estimator
    if _token_estimator is None:
        _token_estimator = TokenEstimator()
    return _token_estimator


def truncate_to_tokens(
    text: str,
    max_tokens: int,
    suffix: str = "\n... [truncated]",
) -> str:
    """
    Convenience function to truncate text using the global TokenEstimator.

    Args:
        text: The text to potentially truncate
        max_tokens: Maximum number of tokens allowed
        suffix: String to append if truncation occurs (not counted toward limit)

    Returns:
        Original text if within limit, otherwise truncated text with suffix
    """
    return get_token_estimator().truncate_to_tokens(text, max_tokens, suffix)
