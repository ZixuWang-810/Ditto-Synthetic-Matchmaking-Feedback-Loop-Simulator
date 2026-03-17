"""Tests for repair_json function and MatchScorer LLM fallback behavior.

Covers:
1. The exact bug from the error log (unescaped quotes + truncated output)
2. Truncated JSON with unclosed brackets
3. Trailing comma in array
4. Markdown code fences
5. Already-valid JSON (no repair needed)
6. Completely unparseable input
7. MatchScorer._llm_compatibility_score() fallback when generate_structured raises ValueError
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.llm.client import repair_json
from src.ditto_bot.matcher import CompatibilityScore, MatchScorer
from src.models.persona import (
    Persona,
    DatingPreferences,
    Gender,
    DateType,
    DegreeLevel,
    CommunicationStyle,
    PreferenceStrictness,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def user_persona():
    """Minimal valid Persona for use in matcher tests."""
    return Persona(
        name="Emily Torres",
        age=20,
        gender=Gender.FEMALE,
        ethnicity="Latina",
        height_inches=65,
        hobbies=["photography", "cooking", "studying"],
        degree_level=DegreeLevel.SOPHOMORE,
        date_type=DateType.SERIOUS_RELATIONSHIP,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.MALE],
            preferred_age_min=19,
            preferred_age_max=25,
        ),
        communication_style=CommunicationStyle.RESERVED,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="Pre-med student who loves capturing moments through a lens.",
    )


@pytest.fixture
def candidate_persona():
    """Minimal valid Persona for use as a match candidate."""
    return Persona(
        name="Juan Reyes",
        age=21,
        gender=Gender.MALE,
        ethnicity="Latino",
        height_inches=70,
        hobbies=["photography", "cooking", "gaming"],
        degree_level=DegreeLevel.JUNIOR,
        date_type=DateType.CASUAL_DATES,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.FEMALE],
            preferred_age_min=18,
            preferred_age_max=24,
        ),
        communication_style=CommunicationStyle.ENTHUSIASTIC,
        preference_strictness=PreferenceStrictness.OPEN,
        bio="Engineering student who stays up all night and loves street food.",
    )


# ── Test 1: Exact bug from error log ─────────────────────────────────────────

def test_exact_bug_from_error_log():
    """The raw truncated LLM response from the bug report.

    Contains:
    - Unescaped single quotes in "Juan's" (fine for JSON)
    - Unescaped double quote inside "5'5"" (breaks JSON)
    - Truncated output — missing closing brackets and braces
    """
    raw = (
        '{\n'
        '  "score": 0.65,\n'
        '  "justification": "Date types align as both are looking for serious relationships, '
        "shared interests include photography and cooking, but Juan's casual all-nighter habits "
        "may clash with Emily's need for a partner who appreciates her studious nature.\",\n"
        '  "shared_interests": [\n'
        '    "photography",\n'
        '    "cooking"\n'
        '  ],\n'
        '  "potential_issues": [\n'
        '    "different study habits",\n'
        '    "height difference (5\'5"'
    )

    result = repair_json(raw)

    assert result is not None, "repair_json should return a dict, not None"
    assert isinstance(result, dict), "repair_json should return a dict"
    assert result["score"] == 0.65, f"Expected score=0.65, got {result['score']}"
    assert "justification" in result, "Result should contain 'justification' key"
    assert "shared_interests" in result, "Result should contain 'shared_interests' key"
    assert "potential_issues" in result, "Result should contain 'potential_issues' key"


# ── Test 2: Truncated output with unclosed brackets ───────────────────────────

def test_truncated_unclosed_brackets():
    """JSON cut off mid-array — _close_brackets should add missing ] and }."""
    raw = '{"score": 0.7, "justification": "good match", "shared_interests": ["hiking"'

    result = repair_json(raw)

    assert result is not None, "repair_json should handle truncated JSON"
    assert isinstance(result, dict)
    assert result["score"] == 0.7
    assert result["justification"] == "good match"
    assert "hiking" in result["shared_interests"]


# ── Test 3: Trailing comma ────────────────────────────────────────────────────

def test_trailing_comma():
    """Trailing comma before ] is invalid JSON — should be stripped."""
    raw = '{"score": 0.8, "items": ["a", "b",]}'

    result = repair_json(raw)

    assert result is not None, "repair_json should handle trailing commas"
    assert isinstance(result, dict)
    assert result["score"] == 0.8
    assert result["items"] == ["a", "b"]


# ── Test 4: Markdown code fences ──────────────────────────────────────────────

def test_markdown_fences():
    """LLM wraps JSON in ```json ... ``` — should be extracted and parsed."""
    raw = '```json\n{"score": 0.5}\n```'

    result = repair_json(raw)

    assert result is not None, "repair_json should strip markdown fences"
    assert isinstance(result, dict)
    assert result["score"] == 0.5


# ── Test 5: Already valid JSON ────────────────────────────────────────────────

def test_already_valid_json():
    """Valid JSON should parse correctly without any repair needed."""
    raw = '{"score": 0.9, "justification": "great"}'

    result = repair_json(raw)

    assert result is not None, "repair_json should return dict for valid JSON"
    assert isinstance(result, dict)
    assert result["score"] == 0.9
    assert result["justification"] == "great"


# ── Test 6: Completely unparseable ────────────────────────────────────────────

def test_completely_unparseable():
    """Plain text with no JSON structure — should return None."""
    raw = "I cannot generate JSON"

    result = repair_json(raw)

    assert result is None, "repair_json should return None for unparseable input"


# ── Test 7: MatchScorer fallback on ValueError ────────────────────────────────

def test_matcher_fallback_on_value_error(user_persona, candidate_persona):
    """When generate_structured raises ValueError, _llm_compatibility_score
    should return a CompatibilityScore with score=0.5 and 'scoring_unavailable'
    in potential_issues — never propagate the exception.
    """
    # Create a mock LLMClient whose generate_structured always raises ValueError
    mock_client = MagicMock()
    mock_client.generate_structured.side_effect = ValueError(
        "Failed to parse structured output after all retries"
    )

    # Inject the mock client directly — no real Ollama calls
    scorer = MatchScorer(llm_client=mock_client)

    result = scorer._llm_compatibility_score(
        user=user_persona,
        candidate=candidate_persona,
        rejection_reasons=[],
    )

    assert isinstance(result, CompatibilityScore), (
        f"Expected CompatibilityScore, got {type(result)}"
    )
    assert result.score == 0.5, (
        f"Fallback score should be 0.5 (neutral), got {result.score}"
    )
    assert "scoring_unavailable" in result.potential_issues, (
        f"'scoring_unavailable' should be in potential_issues, got {result.potential_issues}"
    )
    # Verify generate_structured was actually called (not silently skipped)
    mock_client.generate_structured.assert_called_once()
