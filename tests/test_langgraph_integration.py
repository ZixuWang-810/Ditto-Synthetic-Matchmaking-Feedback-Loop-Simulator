"""Smoke tests for the LangGraph integration.

These tests verify structure, imports, and initialization only.
No running Ollama instance is required — no LLM calls are made.
"""

from __future__ import annotations

import typing
from unittest.mock import MagicMock

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_persona(name: str = "Alex Chen", gender_val: str = "male"):
    """Create a minimal valid Persona for use in tests."""
    from src.models.persona import (
        CommunicationStyle,
        DateType,
        DatingPreferences,
        DegreeLevel,
        Gender,
        Persona,
        PreferenceStrictness,
    )

    gender = Gender(gender_val)
    return Persona(
        name=name,
        age=21,
        gender=gender,
        ethnicity="East Asian",
        height_inches=71,
        hobbies=["basketball", "coding", "cooking"],
        degree_level=DegreeLevel.JUNIOR,
        date_type=DateType.SERIOUS_RELATIONSHIP,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.FEMALE],
            preferred_age_min=19,
            preferred_age_max=24,
        ),
        communication_style=CommunicationStyle.DIRECT,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="CS major who can cook a mean stir fry. Looking for someone real.",
    )


# ── Test 1: Graph compiles ────────────────────────────────────────────────────


def test_graph_compiles():
    """build_ditto_graph() returns a compiled LangGraph StateGraph with all expected nodes."""
    from langgraph.graph.state import CompiledStateGraph

    from src.ditto_bot.graph import build_ditto_graph

    graph = build_ditto_graph()

    # Must be a compiled graph object
    assert isinstance(graph, CompiledStateGraph), (
        f"Expected CompiledStateGraph, got {type(graph)}"
    )

    # Verify all expected node names are present
    node_names = set(graph.nodes.keys())

    expected_nodes = {
        "__start__",
        "greeting",
        "collect_preferences",
        "score_matches",
        "present_match",
        "handle_rejection",
        "date_proposal",
        "collect_feedback",
    }

    missing = expected_nodes - node_names
    assert not missing, f"Graph is missing expected nodes: {missing}"


# ── Test 2: DittoState schema ─────────────────────────────────────────────────


def test_state_schema():
    """DittoState TypedDict has all required fields and accepts correctly-typed values."""
    from langchain_core.messages import AIMessage, HumanMessage

    from src.ditto_bot.graph import DittoState

    persona = _make_persona()
    persona_dict = persona.model_dump()

    # Build a fully-populated DittoState dict
    state: DittoState = {
        "messages": [
            HumanMessage(content="Hello!"),
            AIMessage(content="Hi there, welcome to Ditto!"),
        ],
        "phase": "collecting_preferences",
        "user_persona": persona_dict,
        "persona_pool": [persona_dict],
        "user_preferences": ["looking for someone kind"],
        "rejection_reasons": [],
        "shown_match_ids": [],
        "current_match": None,
        "accepted_match": None,
        "current_round": 0,
        "max_rounds": 6,
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
    }

    # Verify all annotated fields are present in the state dict
    annotated_fields = set(typing.get_type_hints(DittoState).keys())
    state_keys = set(state.keys())

    missing_fields = annotated_fields - state_keys
    assert not missing_fields, f"State dict is missing fields: {missing_fields}"

    extra_fields = state_keys - annotated_fields
    assert not extra_fields, f"State dict has unexpected extra fields: {extra_fields}"

    # Spot-check types
    assert isinstance(state["messages"], list)
    assert isinstance(state["phase"], str)
    assert isinstance(state["user_persona"], dict)
    assert isinstance(state["persona_pool"], list)
    assert isinstance(state["user_preferences"], list)
    assert isinstance(state["rejection_reasons"], list)
    assert isinstance(state["shown_match_ids"], list)
    assert state["current_match"] is None  # Optional[dict]
    assert state["accepted_match"] is None  # Optional[dict]
    assert isinstance(state["current_round"], int)
    assert isinstance(state["max_rounds"], int)
    assert isinstance(state["llm_model"], str)
    assert isinstance(state["embedding_model"], str)

    # Verify message objects are correct types
    assert isinstance(state["messages"][0], HumanMessage)
    assert isinstance(state["messages"][1], AIMessage)


# ── Test 3: All node functions are callable ───────────────────────────────────


def test_all_nodes_callable():
    """All 7 LangGraph node functions can be imported and are callable."""
    from src.ditto_bot.nodes import (
        collect_feedback_node,
        collect_preferences_node,
        date_proposal_node,
        greeting_node,
        handle_rejection_node,
        present_match_node,
        score_matches_node,
    )

    node_functions = [
        greeting_node,
        collect_preferences_node,
        score_matches_node,
        present_match_node,
        handle_rejection_node,
        date_proposal_node,
        collect_feedback_node,
    ]

    assert len(node_functions) == 7, "Expected exactly 7 node functions"

    for fn in node_functions:
        assert callable(fn), f"{fn!r} is not callable"


# ── Test 4: SimulationEngine initializes correctly ────────────────────────────


def test_engine_init():
    """SimulationEngine initializes without errors given a small persona pool.

    LLMClient uses lazy Ollama initialization — no network calls happen during
    __init__, so no Ollama instance is required for this test.
    """
    from src.orchestrator.engine import SimulationEngine

    # Build a small pool of 3 personas
    personas = [
        _make_persona("Alice", "female"),
        _make_persona("Bob", "male"),
        _make_persona("Charlie", "male"),
    ]

    # Pass a mock LLM client so we never touch the network even accidentally
    mock_client = MagicMock()
    mock_client.model = "llama3.2"
    mock_client.embedding_model = "nomic-embed-text"

    engine = SimulationEngine(
        persona_pool=personas,
        llm_client=mock_client,
        mongo_enabled=False,
    )

    # Verify the engine initialized correctly
    assert engine is not None
    assert hasattr(engine, "persona_pool"), "Engine missing 'persona_pool' attribute"
    assert len(engine.persona_pool) == 3

    assert hasattr(engine, "_ditto_graph"), "Engine missing '_ditto_graph' attribute"
    assert hasattr(engine, "client"), "Engine missing 'client' attribute"
    assert hasattr(engine, "logger"), "Engine missing 'logger' attribute"

    # The compiled graph should be present and be a CompiledStateGraph
    from langgraph.graph.state import CompiledStateGraph

    assert isinstance(engine._ditto_graph, CompiledStateGraph), (
        f"Expected CompiledStateGraph, got {type(engine._ditto_graph)}"
    )


# ── Regression Tests: Bug Fixes ───────────────────────────────────────────────


# ── Regression Test 1: Graph routing after preference collection ──────────────


def test_route_after_collect_preferences_transitions_to_score_matches():
    """route_after_collect_preferences returns 'score_matches' when phase='presenting_match'.

    Regression: After collect_preferences_node completes and sets
    phase='presenting_match', the conditional edge must chain directly into
    score_matches (not END) so current_match is populated before the user
    responds.
    """
    from langgraph.graph import END

    from src.ditto_bot.graph import DittoState, route_after_collect_preferences

    persona = _make_persona()
    persona_dict = persona.model_dump()

    # Simulate state after collect_preferences_node sets phase='presenting_match'
    state: DittoState = {
        "messages": [],
        "phase": "presenting_match",
        "user_persona": persona_dict,
        "persona_pool": [persona_dict],
        "user_preferences": ["looking for someone kind"],
        "rejection_reasons": [],
        "shown_match_ids": [],
        "current_match": None,  # score_matches hasn't run yet
        "accepted_match": None,
        "current_round": 0,
        "max_rounds": 6,
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
    }

    result = route_after_collect_preferences(state)
    assert result == "score_matches", (
        f"Expected 'score_matches' when phase='presenting_match', got {result!r}"
    )


def test_route_after_collect_preferences_returns_end_when_still_collecting():
    """route_after_collect_preferences returns END when phase='collecting_preferences'.

    Regression: When preferences are still being gathered, the graph must
    return END so the orchestrator can deliver Ditto's follow-up question
    and wait for the next user message.
    """
    from langgraph.graph import END

    from src.ditto_bot.graph import DittoState, route_after_collect_preferences

    persona = _make_persona()
    persona_dict = persona.model_dump()

    # Simulate state where preferences are still being collected
    state: DittoState = {
        "messages": [],
        "phase": "collecting_preferences",
        "user_persona": persona_dict,
        "persona_pool": [persona_dict],
        "user_preferences": [],
        "rejection_reasons": [],
        "shown_match_ids": [],
        "current_match": None,
        "accepted_match": None,
        "current_round": 0,
        "max_rounds": 6,
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
    }

    result = route_after_collect_preferences(state)
    assert result == END, (
        f"Expected END when phase='collecting_preferences', got {result!r}"
    )


# ── Regression Test 2: Acceptance signal requires current_match ───────────────


def test_route_after_user_response_no_current_match_routes_to_score_matches():
    """route_after_user_response routes to 'score_matches' when current_match is None.

    Regression: When phase='presenting_match' but current_match is None
    (score_matches hasn't run yet), the router must NOT check acceptance
    signals — it must route to 'score_matches' first.  Without this guard,
    a message like 'yes sounds great' would incorrectly route to 'date_proposal'
    with no match data.
    """
    from langchain_core.messages import HumanMessage

    from src.ditto_bot.graph import DittoState, route_after_user_response

    persona = _make_persona()
    persona_dict = persona.model_dump()

    # Acceptance-like message, but current_match is None
    state: DittoState = {
        "messages": [HumanMessage(content="yes sounds great")],
        "phase": "presenting_match",
        "user_persona": persona_dict,
        "persona_pool": [persona_dict],
        "user_preferences": ["looking for someone kind"],
        "rejection_reasons": [],
        "shown_match_ids": [],
        "current_match": None,  # score_matches hasn't run yet
        "accepted_match": None,
        "current_round": 0,
        "max_rounds": 6,
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
    }

    result = route_after_user_response(state)
    assert result == "score_matches", (
        f"Expected 'score_matches' when current_match is None, got {result!r}. "
        "Acceptance signals must not be checked before current_match is populated."
    )


def test_route_after_user_response_with_current_match_routes_to_date_proposal():
    """route_after_user_response routes to 'date_proposal' when current_match is set and user accepts.

    Regression: Once current_match is populated, a genuine acceptance signal
    ('yes sounds great') must route to 'date_proposal'.
    """
    from langchain_core.messages import HumanMessage

    from src.ditto_bot.graph import DittoState, route_after_user_response

    user_persona = _make_persona("Alex Chen", "male")
    candidate_persona = _make_persona("Sarah Kim", "female")
    user_dict = user_persona.model_dump()
    candidate_dict = candidate_persona.model_dump()

    # current_match is populated — score_matches has already run
    state: DittoState = {
        "messages": [HumanMessage(content="yes sounds great")],
        "phase": "presenting_match",
        "user_persona": user_dict,
        "persona_pool": [candidate_dict],
        "user_preferences": ["looking for someone kind"],
        "rejection_reasons": [],
        "shown_match_ids": [],
        "current_match": candidate_dict,  # score_matches has run
        "accepted_match": None,
        "current_round": 1,
        "max_rounds": 6,
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
    }

    result = route_after_user_response(state)
    assert result == "date_proposal", (
        f"Expected 'date_proposal' when current_match is set and user accepts, got {result!r}"
    )


# ── Regression Test 3: False positive acceptance signals removed ──────────────


def test_acceptance_signals_no_false_positives():
    """_ACCEPTANCE_SIGNALS does not contain casual words that cause false positives.

    Regression: Words like 'ok', 'okay', 'great', 'perfect', 'awesome' were
    removed from _ACCEPTANCE_SIGNALS because they appear as substrings in
    non-acceptance messages (e.g. 'that sounds okay but I'm not sure').
    Only intentional acceptance phrases should remain.
    """
    from src.ditto_bot.graph import _ACCEPTANCE_SIGNALS

    false_positive_words = ("ok", "okay", "great", "perfect", "awesome")

    for word in false_positive_words:
        assert word not in _ACCEPTANCE_SIGNALS, (
            f"'{word}' should NOT be in _ACCEPTANCE_SIGNALS — it causes false "
            f"positive acceptance detection via substring matching."
        )


def test_acceptance_signals_contains_intentional_phrases():
    """_ACCEPTANCE_SIGNALS still contains genuine acceptance phrases.

    Sanity check: ensure the tuple wasn't accidentally emptied when removing
    false positives.
    """
    from src.ditto_bot.graph import _ACCEPTANCE_SIGNALS

    # These are unambiguous acceptance phrases that should remain
    expected_phrases = ("yes", "i accept", "absolutely", "sure")

    for phrase in expected_phrases:
        assert phrase in _ACCEPTANCE_SIGNALS, (
            f"'{phrase}' should be in _ACCEPTANCE_SIGNALS as a genuine acceptance signal."
        )

    assert len(_ACCEPTANCE_SIGNALS) > 0, "_ACCEPTANCE_SIGNALS must not be empty"


# ── Regression Test 4: Embedding fallback ────────────────────────────────────


def test_match_scorer_embedding_fallback_returns_results():
    """MatchScorer.score_candidates returns results when embedding call raises Exception.

    Regression: When the embedding model is unavailable (e.g. nomic-embed-text
    not pulled), score_candidates must not raise — it must fall back to 100%
    LLM-based scoring.  embedding_score should be 0.0 and combined_score
    should equal llm_score.
    """
    from unittest.mock import MagicMock, patch

    from src.ditto_bot.matcher import CompatibilityScore, MatchScorer
    from src.models.persona import (
        CommunicationStyle,
        DateType,
        DatingPreferences,
        DegreeLevel,
        Gender,
        Persona,
        PreferenceStrictness,
    )

    # Build minimal valid user and candidate personas
    user = Persona(
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
        ),
        communication_style=CommunicationStyle.DIRECT,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="CS major who can cook a mean stir fry.",
    )

    candidate = Persona(
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
        bio="Data nerd who makes amazing cupcakes.",
    )

    # Mock LLM client: embed raises, generate_structured returns a valid score
    mock_client = MagicMock()
    mock_client.embed.side_effect = Exception("nomic-embed-text not available")
    mock_llm_score = 0.75
    mock_client.generate_structured.return_value = CompatibilityScore(
        score=mock_llm_score,
        justification="Good compatibility based on shared interests.",
        shared_interests=["coding"],
        potential_issues=[],
    )

    scorer = MatchScorer(llm_client=mock_client)
    results = scorer.score_candidates(user=user, candidates=[candidate])

    # Must return results, not raise
    assert results is not None, "score_candidates must not return None"
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"

    result = results[0]

    # embedding_score must be 0.0 (fallback value)
    assert result.embedding_score == 0.0, (
        f"Expected embedding_score=0.0 on fallback, got {result.embedding_score}"
    )

    # combined_score must equal llm_score (100% LLM weight when embeddings fail)
    assert result.combined_score == mock_llm_score, (
        f"Expected combined_score={mock_llm_score} (100% LLM weight), "
        f"got {result.combined_score}"
    )

    # llm_score must match what the mock returned
    assert result.llm_score == mock_llm_score, (
        f"Expected llm_score={mock_llm_score}, got {result.llm_score}"
    )


# ── Regression Tests: Pool Exhaustion & Termination Bug Fixes ─────────────────


def test_route_after_scoring_no_candidates():
    """route_after_scoring returns 'completed' when current_match is None.

    Regression: When score_matches_node finds no eligible candidates it sets
    current_match=None.  route_after_scoring must detect this and route to
    'completed' (END) rather than 'present_match', preventing an infinite loop.
    """
    from src.ditto_bot.graph import route_after_scoring

    state = {
        "current_match": None,
        "current_round": 1,
        "max_rounds": 6,
        "phase": "presenting_match",
        "messages": [],
    }

    result = route_after_scoring(state)
    assert result == "completed", (
        f"Expected 'completed' when current_match is None, got {result!r}. "
        "Pool exhaustion must terminate the conversation."
    )


def test_route_after_scoring_has_candidate():
    """route_after_scoring returns 'present_match' when a candidate is available.

    Sanity check: the normal path (match found, rounds remaining) must still
    route to 'present_match'.
    """
    from src.ditto_bot.graph import route_after_scoring

    state = {
        "current_match": {"id": "test", "name": "Test"},
        "current_round": 1,
        "max_rounds": 6,
        "phase": "presenting_match",
        "messages": [],
    }

    result = route_after_scoring(state)
    assert result == "present_match", (
        f"Expected 'present_match' when a candidate is available and rounds remain, "
        f"got {result!r}."
    )


def test_route_after_scoring_max_rounds_exceeded():
    """route_after_scoring returns 'completed' when max rounds are exhausted.

    Regression: When current_round >= max_rounds the conversation must end even
    if a candidate is technically available, preventing the user from seeing
    more matches than the configured limit.
    """
    from src.ditto_bot.graph import route_after_scoring

    state = {
        "current_match": {"id": "test"},
        "current_round": 6,
        "max_rounds": 6,
        "phase": "presenting_match",
        "messages": [],
    }

    result = route_after_scoring(state)
    assert result == "completed", (
        f"Expected 'completed' when current_round >= max_rounds, got {result!r}. "
        "Max-rounds limit must terminate the conversation."
    )


def test_score_matches_node_empty_pool():
    """score_matches_node sets phase='completed' and current_match=None when pool is empty.

    Regression: When MatchScorer.score_candidates returns an empty list (all
    candidates filtered or pool exhausted), score_matches_node must set
    phase='completed' and current_match=None so that route_after_scoring can
    cleanly terminate the graph.
    """
    from unittest.mock import patch

    from src.ditto_bot.nodes import score_matches_node
    from src.models.persona import (
        CommunicationStyle,
        DateType,
        DatingPreferences,
        DegreeLevel,
        Gender,
        Persona,
        PreferenceStrictness,
    )

    user_persona = Persona(
        name="Alex Chen",
        age=21,
        gender=Gender.MALE,
        ethnicity="East Asian",
        height_inches=71,
        hobbies=["basketball", "coding"],
        degree_level=DegreeLevel.JUNIOR,
        date_type=DateType.SERIOUS_RELATIONSHIP,
        dating_preferences=DatingPreferences(
            preferred_genders=[Gender.FEMALE],
            preferred_age_min=19,
            preferred_age_max=24,
        ),
        communication_style=CommunicationStyle.DIRECT,
        preference_strictness=PreferenceStrictness.MODERATE,
        bio="CS major.",
    )

    state = {
        "messages": [],
        "user_persona": user_persona.model_dump(mode="json"),
        "persona_pool": [],
        "current_round": 0,
        "max_rounds": 6,
        "shown_match_ids": [],
        "rejection_reasons": [],
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
        "phase": "presenting_match",
        "current_match": None,
        "accepted_match": None,
        "user_preferences": [],
    }

    with patch(
        "src.ditto_bot.nodes.MatchScorer.score_candidates",
        return_value=[],
    ):
        result = score_matches_node(state)

    assert result.get("phase") == "completed", (
        f"Expected phase='completed' when pool is empty, got {result.get('phase')!r}."
    )
    assert result.get("current_match") is None, (
        f"Expected current_match=None when pool is empty, got {result.get('current_match')!r}."
    )


def test_embedding_auto_pull_flag_exists():
    """LLMClient has a class-level _embedding_model_verified flag.

    Regression: The auto-pull pattern for the embedding model relies on a
    class-level boolean flag ``_embedding_model_verified`` to ensure the model
    is only pulled once per process.  This test verifies the attribute exists
    on the class (not just on instances) so the fast-path short-circuit works.
    """
    from src.llm.client import LLMClient

    assert hasattr(LLMClient, "_embedding_model_verified"), (
        "LLMClient must have a class-level '_embedding_model_verified' attribute "
        "for the embedding auto-pull fast-path to work correctly."
    )
