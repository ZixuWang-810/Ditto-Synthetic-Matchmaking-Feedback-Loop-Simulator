"""Unit tests for the orchestrator logger."""

import tempfile
import json
from pathlib import Path

import pytest
from src.models.persona import (
    Persona, DatingPreferences, Gender, DateType, DegreeLevel,
    CommunicationStyle, PreferenceStrictness,
)
from src.models.conversation import (
    ConversationLog, Turn, TurnRole, MatchPresented, SentimentLabel,
)
from src.orchestrator.logger import ConversationLogger


@pytest.fixture
def sample_persona():
    return Persona(
        name="Test User",
        age=20,
        gender=Gender.FEMALE,
        ethnicity="White",
        height_inches=65,
        hobbies=["reading", "gaming"],
        degree_level=DegreeLevel.SOPHOMORE,
        date_type=DateType.CASUAL_DATES,
        dating_preferences=DatingPreferences(preferred_genders=[Gender.MALE]),
        communication_style=CommunicationStyle.ENTHUSIASTIC,
        preference_strictness=PreferenceStrictness.OPEN,
        bio="Bookworm gamer",
    )


@pytest.fixture
def sample_conversation_log(sample_persona):
    return ConversationLog(
        persona=sample_persona,
        turns=[
            Turn(role=TurnRole.DITTO, content="Hey there! Welcome to Ditto 💛"),
            Turn(role=TurnRole.USER, content="Hi! I'm looking for someone fun"),
            Turn(role=TurnRole.DITTO, content="I found someone great for you!"),
            Turn(role=TurnRole.USER, content="Sure, sounds good!"),
        ],
        matches_presented=[
            MatchPresented(
                match_id="match-001",
                match_name="John Doe",
                round=1,
                accepted=True,
                justification="Shared love of gaming",
            ),
        ],
        sentiment_trajectory=[SentimentLabel.NEUTRAL, SentimentLabel.EXCITED],
        rounds_to_acceptance=1,
        post_date_rating=4,
        post_date_feedback="Had a great time! He was really funny.",
        total_rounds=1,
    )


class TestConversationLogger:
    def test_log_and_load(self, sample_conversation_log):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logger = ConversationLogger(output_dir=Path(tmp_dir))
            logger.log_conversation(sample_conversation_log)

            assert logger.logged_count == 1

            loaded = ConversationLogger.load_conversations(logger.log_file_path)
            assert len(loaded) == 1
            assert loaded[0].conversation_id == sample_conversation_log.conversation_id
            assert loaded[0].post_date_rating == 4
            assert len(loaded[0].turns) == 4

    def test_multiple_logs(self, sample_conversation_log):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logger = ConversationLogger(output_dir=Path(tmp_dir))

            for _ in range(3):
                logger.log_conversation(sample_conversation_log)

            assert logger.logged_count == 3

            loaded = ConversationLogger.load_conversations(logger.log_file_path)
            assert len(loaded) == 3

    def test_schema_compliance(self, sample_conversation_log):
        """Verify the JSONL output contains all fields from the roadmap schema."""
        json_str = sample_conversation_log.model_dump_json()
        data = json.loads(json_str)

        required_fields = [
            "conversation_id", "persona", "turns", "matches_presented",
            "rejection_reasons", "sentiment_trajectory",
            "rounds_to_acceptance", "post_date_rating",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # Verify turn structure
        assert data["turns"][0]["role"] in ("ditto", "user")
        assert "content" in data["turns"][0]

        # Verify match structure
        match = data["matches_presented"][0]
        assert "match_id" in match
        assert "round" in match
        assert "accepted" in match
