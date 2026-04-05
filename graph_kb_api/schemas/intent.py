"""
Pydantic schemas for intent detection.
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """Result of intent classification."""

    intent: str
    confidence: float
    params: Dict[str, Any] = Field(default_factory=dict)


class IntentConfig(BaseModel):
    """Configuration for an intent handler."""

    handler: str
    required_params: List[str] = Field(default_factory=list)
    optional_params: List[str] = Field(default_factory=list)
