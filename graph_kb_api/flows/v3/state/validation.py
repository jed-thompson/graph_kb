"""
State validation utilities for LangGraph v3 workflows.

These utilities provide validation, type checking, and repair functionality
for workflow state to ensure state integrity throughout execution.
"""

from typing import Any, Dict, List, Optional, Tuple

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class StateValidationError(Exception):
    """Exception raised when state validation fails."""
    pass


class ValidationResult:
    """Result of state validation."""

    def __init__(
        self,
        is_valid: bool,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []

    def add_error(self, error: str) -> None:
        """Add an error to the validation result."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning to the validation result."""
        self.warnings.append(warning)

    def __bool__(self) -> bool:
        """Return True if validation passed."""
        return self.is_valid

    def __str__(self) -> str:
        """String representation of validation result."""
        if self.is_valid:
            msg = "State validation passed"
            if self.warnings:
                msg += f" with {len(self.warnings)} warnings"
            return msg
        else:
            return f"State validation failed with {len(self.errors)} errors"


class StateValidator:
    """
    Validator for workflow state with configurable rules.

    This class encapsulates validation rules and provides methods for
    validating, repairing, and checking state transitions. It centralizes
    all validation logic and configuration in one place.

    Example:
        >>> validator = StateValidator()
        >>> result = validator.validate(state)
        >>> if not result.is_valid:
        ...     repaired, repairs = validator.repair(state)
    """

    def __init__(self):
        """Initialize validator with default validation rules."""

        # Required fields that must be present in state
        self.required_fields = [
            'user_id', 'session_id', 'workflow_id', 'thread_id',
            'awaiting_user_input', 'tool_calls_made', 'tool_results',
            'progress_step', 'progress_total', 'success'
        ]

        # Expected types for each field
        self.type_specs = {
            'args': list,
            'repo_id': (str, type(None)),
            'user_id': str,
            'session_id': str,
            'workflow_id': str,
            'thread_id': str,
            'error': (str, type(None)),
            'error_type': (str, type(None)),
            'awaiting_user_input': bool,
            'user_input_type': (str, type(None)),
            'user_prompt': (str, type(None)),
            'user_response': (str, type(None)),
            'tool_calls_made': list,
            'tool_results': list,
            'progress_step': int,
            'progress_total': int,
            'success': bool,
        }

        # Default values for missing fields
        self.defaults = {
            'args': [],
            'repo_id': None,
            'user_id': 'unknown',
            'session_id': 'unknown',
            'workflow_id': 'unknown',
            'thread_id': 'unknown',
            'error': None,
            'error_type': None,
            'awaiting_user_input': False,
            'user_input_type': None,
            'user_prompt': None,
            'user_response': None,
            'tool_calls_made': [],
            'tool_results': [],
            'progress_step': 0,
            'progress_total': 0,
            'success': False,
            'final_output': None,
        }

        # Fields that should never change during workflow execution
        self.immutable_fields = ['workflow_id', 'user_id', 'session_id', 'thread_id']

        # Required string fields that cannot be empty
        self.required_string_fields = ['user_id', 'session_id', 'workflow_id', 'thread_id']

        # Optional string fields (can be None or string, but not other types)
        self.optional_string_fields = [
            'repo_id', 'error', 'error_type', 'user_input_type',
            'user_prompt', 'user_response'
        ]


    def validate(self, state: Dict[str, Any], strict: bool = False) -> ValidationResult:
        """
        Validate workflow state for correctness and completeness.

        Checks:
        - Required fields are present
        - Field types are correct
        - State invariants are maintained
        - No invalid field values

        Args:
            state: State dictionary to validate
            strict: If True, treat warnings as errors

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        result = ValidationResult(is_valid=True)

        # Check required fields
        for field in self.required_fields:
            if field not in state:
                result.add_error(f"Required field '{field}' is missing")

        # Validate field types
        type_errors = self._validate_types(state)
        for error in type_errors:
            result.add_error(error)

        # Check state invariants
        invariant_errors = self._check_invariants(state)
        for error in invariant_errors:
            if strict:
                result.add_error(error)
            else:
                result.add_warning(error)

        # Check for invalid values
        value_errors = self._check_invalid_values(state)
        for error in value_errors:
            result.add_error(error)

        return result

    def _validate_types(self, state: Dict[str, Any]) -> List[str]:
        """
        Validate that state fields have correct types.

        Args:
            state: State dictionary to validate

        Returns:
            List of type validation errors
        """
        errors = []

        for field, expected_type in self.type_specs.items():
            if field in state:
                value = state[field]
                if not isinstance(value, expected_type):
                    if isinstance(expected_type, tuple):
                        type_names = ' or '.join(t.__name__ for t in expected_type)
                        errors.append(
                            f"Field '{field}' has type {type(value).__name__}, "
                            f"expected {type_names}"
                        )
                    else:
                        errors.append(
                            f"Field '{field}' has type {type(value).__name__}, "
                            f"expected {expected_type.__name__}"
                        )

        return errors

    def repair(self, state: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Attempt to repair invalid state by fixing common issues.

        Repairs:
        - Add missing required fields with default values
        - Fix incorrect types where possible
        - Restore state invariants
        - Remove invalid fields

        Args:
            state: State dictionary to repair

        Returns:
            Tuple of (repaired_state, list of repairs made)
        """
        repaired = dict(state)
        repairs = []

        # Add missing required fields with defaults
        for field, default_value in self.defaults.items():
            if field not in repaired:
                repaired[field] = default_value
                repairs.append(f"Added missing field '{field}' with default value")

        # Fix incorrect types for required list fields
        if 'args' in repaired and not isinstance(repaired['args'], list):
            repaired['args'] = []
            repairs.append("Fixed 'args' to be a list")

        if 'tool_calls_made' in repaired and not isinstance(repaired['tool_calls_made'], list):
            repaired['tool_calls_made'] = []
            repairs.append("Fixed 'tool_calls_made' to be a list")

        if 'tool_results' in repaired and not isinstance(repaired['tool_results'], list):
            repaired['tool_results'] = []
            repairs.append("Fixed 'tool_results' to be a list")

        # Fix boolean fields
        if 'awaiting_user_input' in repaired and not isinstance(repaired['awaiting_user_input'], bool):
            repaired['awaiting_user_input'] = bool(repaired['awaiting_user_input'])
            repairs.append("Fixed 'awaiting_user_input' to be a boolean")

        if 'success' in repaired and not isinstance(repaired['success'], bool):
            repaired['success'] = bool(repaired['success'])
            repairs.append("Fixed 'success' to be a boolean")

        # Fix string fields that should not be None (required fields)
        for field in self.required_string_fields:
            if field in repaired:
                value = repaired[field]
                # Fix if not a string or if empty string
                if not isinstance(value, str) or len(value.strip()) == 0:
                    repaired[field] = 'unknown'
                    repairs.append(f"Fixed '{field}' to be a non-empty string")

        # Fix optional string fields (can be None or string, but not other types)
        for field in self.optional_string_fields:
            if field in repaired:
                value = repaired[field]
                if value is not None and not isinstance(value, str):
                    repaired[field] = None
                    repairs.append(f"Fixed '{field}' to be None (was invalid type)")

        # Fix progress values
        if 'progress_step' in repaired:
            if not isinstance(repaired['progress_step'], int):
                try:
                    repaired['progress_step'] = int(repaired['progress_step'])
                    repairs.append("Fixed 'progress_step' to be an integer")
                except (ValueError, TypeError):
                    repaired['progress_step'] = 0
                    repairs.append("Fixed 'progress_step' to be an integer (defaulted to 0)")
            # Ensure progress_step is not negative
            if isinstance(repaired['progress_step'], int) and repaired['progress_step'] < 0:
                repaired['progress_step'] = 0
                repairs.append("Fixed 'progress_step' to be non-negative")

        if 'progress_total' in repaired:
            if not isinstance(repaired['progress_total'], int):
                try:
                    repaired['progress_total'] = int(repaired['progress_total'])
                    repairs.append("Fixed 'progress_total' to be an integer")
                except (ValueError, TypeError):
                    repaired['progress_total'] = 0
                    repairs.append("Fixed 'progress_total' to be an integer (defaulted to 0)")
            # Ensure progress_total is not negative
            if isinstance(repaired['progress_total'], int) and repaired['progress_total'] < 0:
                repaired['progress_total'] = 0
                repairs.append("Fixed 'progress_total' to be non-negative")

        # Ensure progress_step <= progress_total
        if repaired.get('progress_step', 0) > repaired.get('progress_total', 0):
            repaired['progress_step'] = repaired['progress_total']
            repairs.append("Fixed progress_step to not exceed progress_total")

        return repaired, repairs

    def _check_invariants(self, state: Dict[str, Any]) -> List[str]:
        """
        Check state invariants that should always hold.

        Args:
            state: State dictionary to check

        Returns:
            List of invariant violations
        """
        violations = []

        # Progress invariant: step <= total
        progress_step = state.get('progress_step', 0)
        progress_total = state.get('progress_total', 0)

        # Only check if both are integers
        if isinstance(progress_step, int) and isinstance(progress_total, int):
            if progress_step > progress_total:
                violations.append(
                    f"Progress invariant violated: step ({progress_step}) > total ({progress_total})"
                )

        # Tool calls and results should have compatible lengths
        tool_calls = state.get('tool_calls_made', [])
        tool_results = state.get('tool_results', [])

        # Only check if both are lists
        if isinstance(tool_calls, list) and isinstance(tool_results, list):
            if len(tool_calls) > 0 and len(tool_results) > len(tool_calls):
                violations.append(
                    f"Tool results ({len(tool_results)}) exceed tool calls ({len(tool_calls)})"
                )

        # If awaiting user input, user_input_type should be set
        if state.get('awaiting_user_input') and not state.get('user_input_type'):
            violations.append(
                "awaiting_user_input is True but user_input_type is not set"
            )

        # If error is set, error_type should also be set
        if state.get('error') and not state.get('error_type'):
            violations.append(
                "error is set but error_type is not set"
            )

        return violations

    def _check_invalid_values(self, state: Dict[str, Any]) -> List[str]:
        """
        Check for invalid field values.

        Args:
            state: State dictionary to check

        Returns:
            List of invalid value errors
        """
        errors = []

        # Check for empty required strings
        for field in self.required_string_fields:
            if field in state:
                value = state[field]
                if isinstance(value, str) and len(value.strip()) == 0:
                    errors.append(f"Required string field '{field}' is empty")

        # Check for negative progress values (only if they are integers)
        progress_step = state.get('progress_step', 0)
        if isinstance(progress_step, int) and progress_step < 0:
            errors.append("progress_step cannot be negative")

        progress_total = state.get('progress_total', 0)
        if isinstance(progress_total, int) and progress_total < 0:
            errors.append("progress_total cannot be negative")

        return errors

    def get_summary(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a summary of the current state for debugging.

        Args:
            state: State dictionary

        Returns:
            Dictionary with state summary
        """
        return {
            'workflow_id': state.get('workflow_id'),
            'user_id': state.get('user_id'),
            'session_id': state.get('session_id'),
            'progress': f"{state.get('progress_step', 0)}/{state.get('progress_total', 0)}",
            'awaiting_input': state.get('awaiting_user_input', False),
            'has_error': bool(state.get('error')),
            'success': state.get('success', False),
            'tool_calls_count': len(state.get('tool_calls_made', [])),
            'tool_results_count': len(state.get('tool_results', [])),
        }

    def validate_transition(
        self,
        old_state: Dict[str, Any],
        new_state: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate that a state transition is valid.

        Checks:
        - Core fields are not modified
        - Progress only moves forward
        - State changes are logical

        Args:
            old_state: Previous state
            new_state: New state

        Returns:
            ValidationResult with validation status
        """
        result = ValidationResult(is_valid=True)

        # Core fields should not change
        for field in self.immutable_fields:
            if field in old_state and field in new_state:
                if old_state[field] != new_state[field]:
                    result.add_error(
                        f"Immutable field '{field}' was modified: "
                        f"{old_state[field]} -> {new_state[field]}"
                    )

        # Progress should only move forward (only check if both are integers)
        old_progress = old_state.get('progress_step', 0)
        new_progress = new_state.get('progress_step', 0)

        if isinstance(old_progress, int) and isinstance(new_progress, int):
            if new_progress < old_progress:
                result.add_warning(
                    f"Progress moved backward: {old_progress} -> {new_progress}"
                )

        # Tool calls should only accumulate (only check if both are lists)
        old_calls_value = old_state.get('tool_calls_made', [])
        new_calls_value = new_state.get('tool_calls_made', [])

        if isinstance(old_calls_value, list) and isinstance(new_calls_value, list):
            old_calls = len(old_calls_value)
            new_calls = len(new_calls_value)

            if new_calls < old_calls:
                result.add_error(
                    f"Tool calls decreased: {old_calls} -> {new_calls}"
                )

        return result


# Module-level singleton for convenience
_default_validator = StateValidator()


# Convenience functions that delegate to the singleton
# These maintain backward compatibility with existing code

def validate_state(state: Dict[str, Any], strict: bool = False) -> ValidationResult:
    """
    Validate workflow state (convenience function).

    This function delegates to the default StateValidator instance.
    For custom validation rules, create a StateValidator instance directly.

    Args:
        state: State dictionary to validate
        strict: If True, treat warnings as errors

    Returns:
        ValidationResult with validation status
    """
    return _default_validator.validate(state, strict)


def validate_state_types(state: Dict[str, Any]) -> List[str]:
    """
    Validate state field types (convenience function).

    This function delegates to the default StateValidator instance.

    Args:
        state: State dictionary to validate

    Returns:
        List of type validation errors
    """
    return _default_validator._validate_types(state)


def repair_state(state: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Repair invalid state (convenience function).

    This function delegates to the default StateValidator instance.

    Args:
        state: State dictionary to repair

    Returns:
        Tuple of (repaired_state, list of repairs made)
    """
    return _default_validator.repair(state)


def get_state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get state summary (convenience function).

    This function delegates to the default StateValidator instance.

    Args:
        state: State dictionary

    Returns:
        Dictionary with state summary
    """
    return _default_validator.get_summary(state)


def validate_state_transition(
    old_state: Dict[str, Any],
    new_state: Dict[str, Any]
) -> ValidationResult:
    """
    Validate state transition (convenience function).

    This function delegates to the default StateValidator instance.

    Args:
        old_state: Previous state
        new_state: New state

    Returns:
        ValidationResult with validation status
    """
    return _default_validator.validate_transition(old_state, new_state)
