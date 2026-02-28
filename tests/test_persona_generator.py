"""Unit tests for the persona generator (without live LLM calls)."""

import json
import tempfile
from pathlib import Path

import pytest
from src.models.persona import (
    Persona, DatingPreferences, Gender, DateType, DegreeLevel,
    CommunicationStyle, PreferenceStrictness,
)
from src.persona_generator.generator import PersonaGenerator


# ── JSONL Persistence Tests ───────────────────────────────────────────────────

@pytest.fixture
def sample_personas():
    """Create a small list of test personas."""
    base_prefs = DatingPreferences(
        preferred_genders=[Gender.FEMALE],
        preferred_age_min=18,
        preferred_age_max=25,
    )
    return [
        Persona(
            name=f"Student {i}",
            age=19 + i,
            gender=Gender.MALE if i % 2 == 0 else Gender.FEMALE,
            ethnicity="White" if i % 3 == 0 else "East Asian",
            height_inches=65 + i,
            hobbies=["hobby_a", "hobby_b"],
            degree_level=DegreeLevel.FRESHMAN,
            date_type=DateType.CASUAL_DATES,
            dating_preferences=base_prefs,
            communication_style=CommunicationStyle.DIRECT,
            preference_strictness=PreferenceStrictness.OPEN,
            bio=f"I'm student {i}",
        )
        for i in range(5)
    ]


class TestPersonaJSONL:
    def test_write_and_load_jsonl(self, sample_personas):
        """Test JSONL write + read roundtrip."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = Path(f.name)

        generator = PersonaGenerator.__new__(PersonaGenerator)
        generator._write_jsonl(sample_personas, path)

        loaded = PersonaGenerator.load_personas(path)
        assert len(loaded) == 5
        assert loaded[0].name == "Student 0"
        assert loaded[4].name == "Student 4"

        # Cleanup
        path.unlink()

    def test_empty_file_loads_empty(self):
        """Loading an empty file should return an empty list."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = Path(f.name)

        loaded = PersonaGenerator.load_personas(path)
        assert loaded == []

        path.unlink()


class TestDiversityHints:
    def test_empty_pool_gives_general_hint(self):
        generator = PersonaGenerator.__new__(PersonaGenerator)
        hints = generator._compute_diversity_hints([], 100)
        assert "diverse" in hints.lower()

    def test_imbalanced_gender_gives_hint(self, sample_personas):
        # All males — should suggest more females
        all_male = [p for p in sample_personas if p.gender == Gender.MALE]
        # Pad to make it clearly imbalanced
        while len(all_male) < 10:
            p = sample_personas[0].model_copy()
            p.id = f"copy-{len(all_male)}"
            all_male.append(p)

        generator = PersonaGenerator.__new__(PersonaGenerator)
        hints = generator._compute_diversity_hints(all_male, 100)
        assert "female" in hints.lower() or "diverse" in hints.lower() or "variety" in hints.lower()
