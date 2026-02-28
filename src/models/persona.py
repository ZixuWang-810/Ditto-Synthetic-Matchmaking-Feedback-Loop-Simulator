"""Pydantic models for college student dating personas."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"


class DateType(str, Enum):
    LIFE_PARTNER = "life_partner"
    SERIOUS_RELATIONSHIP = "serious_relationship"
    CASUAL_DATES = "casual_dates"
    NEW_FRIENDS = "new_friends"


class DegreeLevel(str, Enum):
    FRESHMAN = "freshman"
    SOPHOMORE = "sophomore"
    JUNIOR = "junior"
    SENIOR = "senior"
    MASTERS = "masters"
    PHD = "phd"


class CommunicationStyle(str, Enum):
    ENTHUSIASTIC = "enthusiastic"
    RESERVED = "reserved"
    SARCASTIC = "sarcastic"
    DIRECT = "direct"
    FLIRTY = "flirty"


class PreferenceStrictness(str, Enum):
    STRICT = "strict"          # Will reject if preferences not met
    MODERATE = "moderate"      # Flexible but has priorities
    OPEN = "open"              # Very open to different types


class DatingPreferences(BaseModel):
    """Who the persona wants to date and their preferences."""

    preferred_genders: list[Gender] = Field(
        description="Gender(s) the persona is interested in dating"
    )
    preferred_ethnicities: list[str] = Field(
        default_factory=list,
        description="Preferred ethnicities; empty means no preference"
    )
    preferred_age_min: int = Field(
        default=18,
        ge=18,
        description="Minimum preferred age"
    )
    preferred_age_max: int = Field(
        default=30,
        le=35,
        description="Maximum preferred age"
    )
    physical_attraction_criteria: list[str] = Field(
        default_factory=list,
        description="Physical traits they find attractive (e.g., 'athletic build', 'tall')"
    )


class Persona(BaseModel):
    """A synthetic college student dating profile."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="Full name")
    age: int = Field(ge=18, le=30, description="Age (18-30)")
    gender: Gender
    ethnicity: str = Field(description="Self-identified ethnicity")
    height_inches: int = Field(ge=55, le=84, description="Height in inches")
    hobbies: list[str] = Field(
        min_length=2,
        max_length=8,
        description="Hobbies and interests"
    )
    degree_level: DegreeLevel
    university: str = Field(default="California State University")
    date_type: DateType = Field(
        description="What kind of connection they're looking for"
    )
    dating_preferences: DatingPreferences
    communication_style: CommunicationStyle = Field(
        description="How they tend to communicate in chat"
    )
    preference_strictness: PreferenceStrictness = Field(
        description="How strict they are about their preferences"
    )
    bio: str = Field(
        max_length=500,
        description="Short bio / self-description"
    )

    def to_profile_summary(self) -> str:
        """Human-readable profile summary for LLM context."""
        height_ft = self.height_inches // 12
        height_in = self.height_inches % 12
        return (
            f"{self.name}, {self.age}, {self.gender.value} | "
            f"{self.ethnicity} | {height_ft}'{height_in}\" | "
            f"{self.degree_level.value} @ {self.university}\n"
            f"Looking for: {self.date_type.value.replace('_', ' ')}\n"
            f"Hobbies: {', '.join(self.hobbies)}\n"
            f"Bio: {self.bio}"
        )

    def to_embedding_text(self) -> str:
        """Text representation optimized for embedding similarity."""
        return (
            f"{self.gender.value} {self.age} {self.ethnicity} "
            f"{self.degree_level.value} "
            f"{self.date_type.value} "
            f"{' '.join(self.hobbies)} "
            f"{' '.join(self.dating_preferences.physical_attraction_criteria)} "
            f"{self.bio}"
        )
