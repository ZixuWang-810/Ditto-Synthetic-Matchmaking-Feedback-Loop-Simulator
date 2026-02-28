"""Unit tests for Pydantic data models."""

import json
import pytest
from src.models.persona import (
    Persona, DatingPreferences, Gender, DateType, DegreeLevel,
    CommunicationStyle, PreferenceStrictness,
)
from src.models.conversation import (
    ConversationLog, Turn, TurnRole, MatchPresented, SentimentLabel,
)
from src.models.feedback import PostDateFeedback, RejectionFeedback


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_preferences():
    return DatingPreferences(
        preferred_genders=[Gender.FEMALE],
        preferred_ethnicities=["East Asian", "White"],
        preferred_age_min=19,
        preferred_age_max=24,
        physical_attraction_criteria=["athletic", "tall"],
    )


@pytest.fixture
def sample_persona(sample_preferences):
    return Persona(
        name="Alex Chen",
        age=21,
        gender=Gender.MALE,
        ethnicity="East Asian",
        height_inches=71,
        hobbies=["basketball", "coding", "cooking"],
        degree_level=DegreeLevel.JUNIOR,
        date_type=DateType.SERIOUS_RELATIONSHIP,
        dating_preferences=sample_preferences,
        communication_style=CommunicationStyle.DIRECT,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="CS major who can cook a mean stir fry. Looking for someone real.",
    )


# ── Persona Tests ─────────────────────────────────────────────────────────────

class TestPersona:
    def test_create_valid_persona(self, sample_persona):
        assert sample_persona.name == "Alex Chen"
        assert sample_persona.age == 21
        assert sample_persona.gender == Gender.MALE
        assert len(sample_persona.hobbies) == 3

    def test_persona_has_uuid_id(self, sample_persona):
        assert sample_persona.id is not None
        assert len(sample_persona.id) == 36  # UUID format

    def test_persona_json_roundtrip(self, sample_persona):
        json_str = sample_persona.model_dump_json()
        restored = Persona.model_validate_json(json_str)
        assert restored.name == sample_persona.name
        assert restored.age == sample_persona.age
        assert restored.dating_preferences.preferred_genders == [Gender.FEMALE]

    def test_persona_profile_summary(self, sample_persona):
        summary = sample_persona.to_profile_summary()
        assert "Alex Chen" in summary
        assert "21" in summary
        assert "junior" in summary
        assert "basketball" in summary

    def test_persona_embedding_text(self, sample_persona):
        text = sample_persona.to_embedding_text()
        assert "male" in text
        assert "basketball" in text
        assert "coding" in text

    def test_age_validation_too_young(self, sample_preferences):
        with pytest.raises(Exception):
            Persona(
                name="Kid", age=15, gender=Gender.MALE, ethnicity="White",
                height_inches=65, hobbies=["a", "b"],
                degree_level=DegreeLevel.FRESHMAN,
                date_type=DateType.NEW_FRIENDS,
                dating_preferences=sample_preferences,
                communication_style=CommunicationStyle.DIRECT,
                preference_strictness=PreferenceStrictness.OPEN,
                bio="Too young",
            )

    def test_age_validation_too_old(self, sample_preferences):
        with pytest.raises(Exception):
            Persona(
                name="Old", age=35, gender=Gender.MALE, ethnicity="White",
                height_inches=70, hobbies=["a", "b"],
                degree_level=DegreeLevel.PHD,
                date_type=DateType.NEW_FRIENDS,
                dating_preferences=sample_preferences,
                communication_style=CommunicationStyle.DIRECT,
                preference_strictness=PreferenceStrictness.OPEN,
                bio="Too old",
            )

    def test_hobbies_min_length(self, sample_preferences):
        with pytest.raises(Exception):
            Persona(
                name="Boring", age=20, gender=Gender.MALE, ethnicity="White",
                height_inches=70, hobbies=["only_one"],
                degree_level=DegreeLevel.SOPHOMORE,
                date_type=DateType.CASUAL_DATES,
                dating_preferences=sample_preferences,
                communication_style=CommunicationStyle.RESERVED,
                preference_strictness=PreferenceStrictness.OPEN,
                bio="Boring",
            )


# ── Conversation Log Tests ────────────────────────────────────────────────────

class TestConversationLog:
    def test_create_minimal_log(self, sample_persona):
        log = ConversationLog(persona=sample_persona)
        assert log.conversation_id is not None
        assert log.turns == []
        assert log.post_date_rating is None

    def test_log_with_turns(self, sample_persona):
        log = ConversationLog(
            persona=sample_persona,
            turns=[
                Turn(role=TurnRole.DITTO, content="Hey there!"),
                Turn(role=TurnRole.USER, content="Hi!"),
            ],
        )
        assert len(log.turns) == 2
        assert log.turns[0].role == TurnRole.DITTO

    def test_log_with_matches(self, sample_persona):
        log = ConversationLog(
            persona=sample_persona,
            matches_presented=[
                MatchPresented(
                    match_id="test-id", match_name="Jane Doe",
                    round=1, accepted=False,
                    justification="Similar interests",
                ),
            ],
            rejection_reasons=["Not my type"],
        )
        assert len(log.matches_presented) == 1
        assert log.matches_presented[0].accepted is False
        assert len(log.rejection_reasons) == 1

    def test_log_json_roundtrip(self, sample_persona):
        log = ConversationLog(
            persona=sample_persona,
            turns=[Turn(role=TurnRole.DITTO, content="Hi!")],
            sentiment_trajectory=[SentimentLabel.NEUTRAL, SentimentLabel.SATISFIED],
            rounds_to_acceptance=2,
            post_date_rating=4,
            total_rounds=2,
        )
        json_str = log.model_dump_json()
        restored = ConversationLog.model_validate_json(json_str)
        assert restored.post_date_rating == 4
        assert restored.rounds_to_acceptance == 2
        assert len(restored.sentiment_trajectory) == 2

    def test_rating_validation(self, sample_persona):
        with pytest.raises(Exception):
            ConversationLog(persona=sample_persona, post_date_rating=6)

        with pytest.raises(Exception):
            ConversationLog(persona=sample_persona, post_date_rating=0)


# ── Feedback Tests ────────────────────────────────────────────────────────────

class TestFeedback:
    def test_post_date_feedback(self):
        feedback = PostDateFeedback(
            rating=4,
            qualitative_feedback="We had a great conversation!",
            would_see_again=True,
        )
        assert feedback.rating == 4

    def test_rejection_feedback(self):
        rejection = RejectionFeedback(
            reason="Not enough shared interests",
            specific_issues=["different music taste", "too quiet"],
            open_to_similar=False,
        )
        assert len(rejection.specific_issues) == 2
        assert not rejection.open_to_similar

    def test_rating_bounds(self):
        with pytest.raises(Exception):
            PostDateFeedback(
                rating=0, qualitative_feedback="Bad", would_see_again=False,
            )
        with pytest.raises(Exception):
            PostDateFeedback(
                rating=6, qualitative_feedback="Too good", would_see_again=True,
            )
