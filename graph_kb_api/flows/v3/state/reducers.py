"""
Custom reducer functions for LangGraph state management.

Reducers control how state fields are updated when multiple nodes
provide values for the same field. These custom reducers provide
specialized merge logic beyond the default operator.add.
"""

from typing import Any, Dict, List, Optional


def merge_dicts_reducer(existing: Optional[Dict[str, Any]], new: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge two dictionaries, with new values overwriting existing ones.

    Args:
        existing: Existing dictionary value (may be None)
        new: New dictionary value to merge (may be None)

    Returns:
        Merged dictionary
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing

    result = existing.copy()
    result.update(new)
    return result


def append_unique_reducer(existing: Optional[List[Any]], new: Optional[List[Any]]) -> List[Any]:
    """
    Append items to a list, avoiding duplicates.

    Args:
        existing: Existing list (may be None)
        new: New items to append (may be None)

    Returns:
        List with unique items
    """
    if existing is None:
        existing = []
    if new is None:
        new = []

    result = existing.copy()
    for item in new:
        if item not in result:
            result.append(item)

    return result


def max_value_reducer(existing: Optional[int], new: Optional[int]) -> int:
    """
    Keep the maximum value between existing and new.

    Args:
        existing: Existing value (may be None)
        new: New value (may be None)

    Returns:
        Maximum value, or 0 if both are None
    """
    if existing is None and new is None:
        return 0
    if existing is None:
        return new
    if new is None:
        return existing

    return max(existing, new)


def concatenate_strings_reducer(existing: Optional[str], new: Optional[str], separator: str = "\n") -> str:
    """
    Concatenate strings with a separator.

    Args:
        existing: Existing string (may be None)
        new: New string to append (may be None)
        separator: Separator to use between strings

    Returns:
        Concatenated string
    """
    if existing is None:
        existing = ""
    if new is None:
        new = ""

    if not existing:
        return new
    if not new:
        return existing

    return f"{existing}{separator}{new}"
