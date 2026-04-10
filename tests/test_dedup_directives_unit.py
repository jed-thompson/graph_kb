"""Unit tests for dedup directive validation.

Tests: valid directives pass through unchanged, directives with non-existent
canonical_section are dropped, directives with non-existent duplicate_in
entries are dropped, directives missing required fields are dropped.

**Validates: Requirements 8.2, 8.3, 8.4**
"""

from __future__ import annotations

import os
import sys

# Import standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies.
_utils_dir = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "graph_kb_api",
    "flows",
    "v3",
    "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))

from dedup_directives import validate_dedup_directives  # noqa: E402

sys.path.pop(0)

MANIFEST_IDS = {"task_001", "task_002", "task_003", "task_004", "task_005"}


class TestValidDirectivesPassThrough:
    """Valid directives pass through unchanged.

    **Validates: Requirement 8.2**
    """

    def test_single_valid_directive(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002", "task_003"],
                "topic": "URL encoding rules",
                "action": "Keep in task_001, cross-ref in task_002 and task_003",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 1
        assert result[0]["canonical_section"] == "task_001"
        assert result[0]["duplicate_in"] == ["task_002", "task_003"]
        assert result[0]["topic"] == "URL encoding rules"
        assert result[0]["action"] == "Keep in task_001, cross-ref in task_002 and task_003"

    def test_multiple_valid_directives(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002"],
                "topic": "Auth flow",
                "action": "Keep in task_001",
            },
            {
                "canonical_section": "task_004",
                "duplicate_in": ["task_005"],
                "topic": "Error mapping",
                "action": "Keep in task_004",
            },
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        result = validate_dedup_directives([], MANIFEST_IDS)
        assert result == []


class TestInvalidCanonicalSectionDropped:
    """Directives with non-existent canonical_section are dropped.

    **Validates: Requirements 8.3, 8.4**
    """

    def test_nonexistent_canonical_section(self):
        raw = [
            {
                "canonical_section": "task_999",
                "duplicate_in": ["task_001"],
                "topic": "Some topic",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_mix_valid_and_invalid_canonical(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002"],
                "topic": "Valid topic",
                "action": "Valid action",
            },
            {
                "canonical_section": "nonexistent",
                "duplicate_in": ["task_003"],
                "topic": "Invalid topic",
                "action": "Invalid action",
            },
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 1
        assert result[0]["canonical_section"] == "task_001"


class TestInvalidDuplicateInDropped:
    """Directives with non-existent duplicate_in entries are dropped.

    **Validates: Requirements 8.3, 8.4**
    """

    def test_nonexistent_duplicate_in_entry(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_999"],
                "topic": "Some topic",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_partial_invalid_duplicate_in(self):
        """If any entry in duplicate_in is invalid, the whole directive is dropped."""
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002", "task_999"],
                "topic": "Some topic",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_empty_duplicate_in_dropped(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": [],
                "topic": "Some topic",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0


class TestMissingFieldsDropped:
    """Directives missing required fields are dropped.

    **Validates: Requirement 8.2**
    """

    def test_missing_topic(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002"],
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_missing_action(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002"],
                "topic": "Some topic",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_missing_canonical_section(self):
        raw = [
            {
                "duplicate_in": ["task_002"],
                "topic": "Some topic",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_missing_duplicate_in(self):
        raw = [
            {
                "canonical_section": "task_001",
                "topic": "Some topic",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_empty_topic_dropped(self):
        raw = [
            {
                "canonical_section": "task_001",
                "duplicate_in": ["task_002"],
                "topic": "",
                "action": "Some action",
            }
        ]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0

    def test_non_dict_entry_dropped(self):
        raw = ["not a dict", 42]
        result = validate_dedup_directives(raw, MANIFEST_IDS)
        assert len(result) == 0
