"""Centralised JSON parsing for LLM responses.

Consolidates 6+ inline JSON-parsing implementations across plan nodes into a
single utility that handles common LLM response quirks.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel, ValidationError

T = TypeVar("T")

# Pre-compiled patterns for performance
_CODE_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)```",
    re.DOTALL,
)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) and return inner content."""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


def _remove_trailing_commas(text: str) -> str:
    """Remove trailing commas before closing braces/brackets."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _try_parse(text: str) -> dict[str, Any] | list[Any]:
    """Attempt to parse *text* as JSON, trying several cleanup strategies."""
    # 1. Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Strip code fences
    stripped = _strip_code_fences(text)
    if stripped != text:
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
        # 2b. Code-fence content with trailing-comma fix
        cleaned = _remove_trailing_commas(stripped)
        if cleaned != stripped:
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                pass

    # 3. Trailing-comma fix on original
    cleaned = _remove_trailing_commas(text)
    if cleaned != text:
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass

    # 4. Partial JSON recovery – extract first { … } block
    obj_match = _JSON_OBJECT_RE.search(text)
    if obj_match:
        candidate = obj_match.group()
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass
        # 4b. Partial with trailing-comma fix
        cleaned = _remove_trailing_commas(candidate)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError("unable to extract JSON")


def _validate_schema(data: Any, schema: type[T], *, strict: bool) -> T:
    """Validate *data* against a Pydantic model or TypedDict *schema*."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            if strict:
                raise ValueError(
                    f"Schema validation failed for {schema.__name__}: {exc}"
                ) from exc
            return data  # type: ignore[return-value]

    # TypedDict – lightweight structural check
    hints = get_type_hints(schema) if hasattr(schema, "__annotations__") else {}
    if hints:
        if not isinstance(data, dict):
            if strict:
                raise ValueError(
                    f"Expected dict for TypedDict {schema.__name__}, got {type(data).__name__}"
                )
            return data  # type: ignore[return-value]
        missing = set(hints) - set(data)
        if missing and strict:
            raise ValueError(
                f"Missing keys for {schema.__name__}: {missing}"
            )
    return data  # type: ignore[return-value]


def parse_json_from_llm(
    response_text: str,
    expected_schema: type[T] | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any] | T:
    """Parse JSON from an LLM response, handling common quirks.

    Handles: markdown code fences (``\\`json ... \\```), trailing commas,
    leading/trailing whitespace, partial JSON recovery.

    Args:
        response_text: Raw LLM response string.
        expected_schema: Optional Pydantic model or TypedDict for validation.
        strict: If True, raise on schema validation failure.

    Returns:
        Parsed dict or validated schema instance.

    Raises:
        ValueError: If JSON cannot be parsed. Message includes first 200 chars
                    of raw response for debugging.
    """
    if not isinstance(response_text, str) or not response_text.strip():
        prefix = repr(response_text)[:200] if response_text else "<empty>"
        raise ValueError(
            f"Cannot parse JSON from LLM response (empty or non-string). "
            f"Raw input: {prefix}"
        )

    text = response_text.strip()

    try:
        data = _try_parse(text)
    except ValueError:
        prefix = response_text[:200]
        raise ValueError(
            f"Failed to parse JSON from LLM response. "
            f"Raw (first 200 chars): {prefix}"
        )

    if expected_schema is not None:
        return _validate_schema(data, expected_schema, strict=strict)

    return data
