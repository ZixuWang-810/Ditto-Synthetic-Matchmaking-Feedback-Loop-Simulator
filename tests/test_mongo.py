"""Unit tests for MongoDB storage layer using mongomock (no real MongoDB needed)."""

import pytest
import mongomock

from src.storage.mongo_client import MongoStorage
from src.models.persona import (
    Persona, DatingPreferences, Gender, DateType, DegreeLevel,
    CommunicationStyle, PreferenceStrictness,
)
from src.models.conversation import (
    ConversationLog, Turn, TurnRole, SentimentLabel,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mongo():
    """Create a MongoStorage backed by mongomock (in-memory)."""
    client = mongomock.MongoClient()
    storage = MongoStorage()
    storage._client = client
    storage._db = client["test_ditto"]
    storage._ensure_indexes()
    yield storage
    client.close()


@pytest.fixture
def sample_preferences():
    return DatingPreferences(
        preferred_genders=[Gender.FEMALE],
        preferred_ethnicities=["East Asian"],
        preferred_age_min=19,
        preferred_age_max=24,
        physical_attraction_criteria=["athletic"],
    )


@pytest.fixture
def sample_persona(sample_preferences):
    return Persona(
        name="Test User",
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
        bio="Test bio here.",
    )


@pytest.fixture
def sample_conversation(sample_persona):
    return ConversationLog(
        persona=sample_persona,
        turns=[
            Turn(role=TurnRole.DITTO, content="Hey there!"),
            Turn(role=TurnRole.USER, content="Hi!"),
        ],
        sentiment_trajectory=[SentimentLabel.NEUTRAL, SentimentLabel.SATISFIED],
        rounds_to_acceptance=1,
        post_date_rating=4,
        total_rounds=1,
    )


# ── Persona Tests ─────────────────────────────────────────────────────────────

class TestMongoPersonas:
    def test_insert_and_load(self, mongo, sample_persona):
        inserted = mongo.insert_personas([sample_persona])
        assert inserted == 1

        loaded = mongo.load_personas()
        assert len(loaded) == 1
        assert loaded[0].name == "Test User"
        assert loaded[0].id == sample_persona.id

    def test_insert_duplicates_skipped(self, mongo, sample_persona):
        mongo.insert_personas([sample_persona])
        inserted = mongo.insert_personas([sample_persona])
        assert inserted == 0
        assert mongo.get_persona_count() == 1

    def test_get_by_id(self, mongo, sample_persona):
        mongo.insert_personas([sample_persona])
        found = mongo.get_persona_by_id(sample_persona.id)
        assert found is not None
        assert found.name == "Test User"

    def test_get_by_id_not_found(self, mongo):
        result = mongo.get_persona_by_id("nonexistent-id")
        assert result is None

    def test_clear_personas(self, mongo, sample_persona):
        mongo.insert_personas([sample_persona])
        assert mongo.get_persona_count() == 1
        mongo.clear_personas()
        assert mongo.get_persona_count() == 0

    def test_persona_count(self, mongo, sample_persona, sample_preferences):
        p2 = Persona(
            name="Another Person",
            age=22,
            gender=Gender.FEMALE,
            ethnicity="White",
            height_inches=65,
            hobbies=["reading", "hiking", "yoga"],
            degree_level=DegreeLevel.SENIOR,
            date_type=DateType.CASUAL_DATES,
            dating_preferences=sample_preferences,
            communication_style=CommunicationStyle.ENTHUSIASTIC,
            preference_strictness=PreferenceStrictness.OPEN,
            bio="Another test.",
        )
        mongo.insert_personas([sample_persona, p2])
        assert mongo.get_persona_count() == 2


# ── Conversation Tests ────────────────────────────────────────────────────────

class TestMongoConversations:
    def test_insert_and_load(self, mongo, sample_conversation):
        result = mongo.insert_conversation(sample_conversation)
        assert result is True

        loaded = mongo.load_conversations()
        assert len(loaded) == 1
        assert loaded[0].post_date_rating == 4
        assert len(loaded[0].turns) == 2

    def test_insert_duplicate_returns_false(self, mongo, sample_conversation):
        mongo.insert_conversation(sample_conversation)
        result = mongo.insert_conversation(sample_conversation)
        assert result is False
        assert mongo.get_conversation_count() == 1

    def test_bulk_insert(self, mongo, sample_conversation):
        inserted = mongo.insert_conversations([sample_conversation])
        assert inserted == 1

    def test_load_with_limit(self, mongo, sample_persona):
        for i in range(5):
            conv = ConversationLog(
                conversation_id=f"test-conv-{i}",
                persona=sample_persona,
                turns=[Turn(role=TurnRole.DITTO, content=f"Message {i}")],
                total_rounds=1,
            )
            result = mongo.insert_conversation(conv)
            assert result is True, f"Failed to insert conversation {i}"

        assert mongo.get_conversation_count() == 5
        loaded = mongo.load_conversations(limit=3)
        assert len(loaded) == 3

    def test_clear_conversations(self, mongo, sample_conversation):
        mongo.insert_conversation(sample_conversation)
        assert mongo.get_conversation_count() == 1
        mongo.clear_conversations()
        assert mongo.get_conversation_count() == 0


# ── Analytics Tests ───────────────────────────────────────────────────────────

class TestMongoAnalytics:
    def test_summary_stats_empty(self, mongo):
        stats = mongo.get_summary_stats()
        assert stats["total_personas"] == 0
        assert stats["total_conversations"] == 0
        assert stats["acceptance_rate"] == 0

    def test_summary_stats(self, mongo, sample_persona, sample_conversation):
        mongo.insert_personas([sample_persona])
        mongo.insert_conversation(sample_conversation)

        stats = mongo.get_summary_stats()
        assert stats["total_personas"] == 1
        assert stats["total_conversations"] == 1
        assert stats["matches_accepted"] == 1
        assert stats["avg_post_date_rating"] == 4.0
        assert stats["acceptance_rate"] == 1.0

    def test_rejection_stats(self, mongo, sample_persona):
        conv = ConversationLog(
            persona=sample_persona,
            turns=[Turn(role=TurnRole.DITTO, content="Hi")],
            rejection_reasons=["Not my type", "Too far away", "Not my type"],
            total_rounds=2,
        )
        mongo.insert_conversation(conv)

        rejections = mongo.get_rejection_stats(top_n=5)
        assert len(rejections) >= 1
