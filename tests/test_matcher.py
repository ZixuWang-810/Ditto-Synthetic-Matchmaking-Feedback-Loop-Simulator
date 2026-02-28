"""Unit tests for the match scorer (without live LLM calls)."""

import pytest
from src.models.persona import (
    Persona, DatingPreferences, Gender, DateType, DegreeLevel,
    CommunicationStyle, PreferenceStrictness,
)
from src.ditto_bot.matcher import MatchScorer


@pytest.fixture
def user_persona():
    return Persona(
        name="Alex Chen",
        age=21,
        gender=Gender.MALE,
        ethnicity="East Asian",
        height_inches=71,
        hobbies=["basketball", "coding", "cooking"],
        degree_level=DegreeLevel.JUNIOR,
        date_type=DateType.SERIOUS_RELATIONSHIP,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.FEMALE],
            preferred_age_min=19,
            preferred_age_max=24,
            physical_attraction_criteria=["athletic"],
        ),
        communication_style=CommunicationStyle.DIRECT,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="CS major who can cook a mean stir fry.",
    )


@pytest.fixture
def good_match():
    return Persona(
        name="Sarah Kim",
        age=20,
        gender=Gender.FEMALE,
        ethnicity="East Asian",
        height_inches=65,
        hobbies=["volleyball", "coding", "baking"],
        degree_level=DegreeLevel.SOPHOMORE,
        date_type=DateType.SERIOUS_RELATIONSHIP,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.MALE],
            preferred_age_min=20,
            preferred_age_max=25,
        ),
        communication_style=CommunicationStyle.ENTHUSIASTIC,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="Data nerd who makes amazing cupcakes",
    )


@pytest.fixture
def bad_match_wrong_gender():
    return Persona(
        name="Mike Johnson",
        age=22,
        gender=Gender.MALE,  # User prefers female
        ethnicity="White",
        height_inches=73,
        hobbies=["football", "gaming"],
        degree_level=DegreeLevel.SENIOR,
        date_type=DateType.CASUAL_DATES,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.FEMALE],
        ),
        communication_style=CommunicationStyle.DIRECT,
        preference_strictness=PreferenceStrictness.OPEN,
        bio="Business bro",
    )


@pytest.fixture
def bad_match_too_old():
    return Persona(
        name="Lisa Park",
        age=28,  # Outside preferred range 19-24
        gender=Gender.FEMALE,
        ethnicity="East Asian",
        height_inches=63,
        hobbies=["yoga", "reading"],
        degree_level=DegreeLevel.PHD,
        date_type=DateType.LIFE_PARTNER,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.MALE],
        ),
        communication_style=CommunicationStyle.RESERVED,
        preference_strictness=PreferenceStrictness.STRICT,
        bio="Deep thinker looking for depth",
    )


class TestHardFilters:
    def test_passes_good_match(self, user_persona, good_match):
        scorer = MatchScorer.__new__(MatchScorer)
        assert scorer._passes_hard_filters(user_persona, good_match) is True

    def test_filters_wrong_gender(self, user_persona, bad_match_wrong_gender):
        scorer = MatchScorer.__new__(MatchScorer)
        assert scorer._passes_hard_filters(user_persona, bad_match_wrong_gender) is False

    def test_filters_too_old(self, user_persona, bad_match_too_old):
        scorer = MatchScorer.__new__(MatchScorer)
        assert scorer._passes_hard_filters(user_persona, bad_match_too_old) is False

    def test_filters_self(self, user_persona):
        """User should not match with themselves."""
        scorer = MatchScorer.__new__(MatchScorer)
        # Same gender as user, so would fail gender filter
        assert scorer._passes_hard_filters(user_persona, user_persona) is False


