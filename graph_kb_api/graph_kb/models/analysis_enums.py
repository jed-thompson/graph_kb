"""Enum types for code understanding and analysis."""

from enum import Enum


class EntryPointType(str, Enum):
    """Types of entry points in a codebase."""

    HTTP_ENDPOINT = "http_endpoint"
    CLI_COMMAND = "cli_command"
    MAIN_FUNCTION = "main_function"
    EVENT_HANDLER = "event_handler"
    SCHEDULED_TASK = "scheduled_task"


class DomainCategory(str, Enum):
    """Categories for domain concepts."""

    ENTITY = "entity"
    SERVICE = "service"
    REPOSITORY = "repository"
    UTILITY = "utility"
    VALUE_OBJECT = "value_object"


class RelationType(str, Enum):
    """Types of relationships between domain concepts."""

    HAS_MANY = "has_many"
    BELONGS_TO = "belongs_to"
    USES = "uses"
    EXTENDS = "extends"


class StepType(str, Enum):
    """Types of steps in a data flow."""

    ENTRY = "entry"
    PROCESS = "process"
    PERSIST = "persist"
    RETURN = "return"
