"""Pydantic models for feedback data."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PostDateFeedback(BaseModel):
    """Structured feedback after a simulated date."""

    rating: int = Field(ge=1, le=5, description="Overall date rating 1-5")
    qualitative_feedback: str = Field(
        description="Free-text feedback about the date experience"
    )
    would_see_again: bool = Field(
        description="Whether they'd want to see this person again"
    )


class RejectionFeedback(BaseModel):
    """Structured feedback when a user rejects a match."""

    reason: str = Field(description="Primary reason for rejection")
    specific_issues: list[str] = Field(
        default_factory=list,
        description="Specific issues mentioned (e.g., 'too far apart in age')"
    )
    open_to_similar: bool = Field(
        default=True,
        description="Whether they're open to similar profiles in the future"
    )
