"""Pydantic models for conversation logs matching the JSONL schema from the roadmap."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.models.persona import Persona


class SentimentLabel(str, Enum):
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    SATISFIED = "satisfied"
    EXCITED = "excited"
    DISAPPOINTED = "disappointed"


class TurnRole(str, Enum):
    DITTO = "ditto"
    USER = "user"


class Turn(BaseModel):
    """A single message turn in a conversation."""

    role: TurnRole
    content: str


class MatchPresented(BaseModel):
    """Record of a match presented during the conversation."""

    match_id: str = Field(description="Persona ID of the presented match")
    match_name: str = Field(description="Name of the presented match")
    round: int = Field(ge=1, description="Which match round this was")
    accepted: bool = Field(description="Whether the user accepted this match")
    justification: str = Field(
        default="",
        description="Natural-language justification for why this match was chosen"
    )


class ConversationLog(BaseModel):
    """Full conversation log matching the roadmap's JSONL schema."""

    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona: Persona = Field(description="The user persona for this conversation")
    turns: list[Turn] = Field(default_factory=list)
    matches_presented: list[MatchPresented] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    sentiment_trajectory: list[SentimentLabel] = Field(default_factory=list)
    rounds_to_acceptance: Optional[int] = Field(
        default=None,
        description="Number of rounds before the user accepted a match (null if never accepted)"
    )
    post_date_rating: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="Post-date rating 1-5 (null if no date happened)"
    )
    post_date_feedback: Optional[str] = Field(
        default=None,
        description="Qualitative post-date feedback"
    )
    dropped_off: bool = Field(
        default=False,
        description="Whether the user dropped off / ghosted"
    )
    total_rounds: int = Field(
        default=0,
        description="Total number of match rounds completed"
    )
