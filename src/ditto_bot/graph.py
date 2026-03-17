from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from src.ditto_bot.agent import ConversationPhase  # re-exported for node functions

__all__ = ["DittoState", "ConversationPhase", "build_ditto_graph"]

# Acceptance signal substrings (case-insensitive).
# Only intentional acceptance phrases are included — common casual words like
# "great", "perfect", "awesome", "ok", "okay" have been removed to prevent
# false positives via substring matching.
_ACCEPTANCE_SIGNALS = (
    "yes",
    "sounds great",
    "let's do it",
    "lets do it",
    "i accept",
    "sure",
    "love it",
    "absolutely",
    "why not",
    "i'd love",
    "id love",
    "down",
    "count me in",
    "let's go",
    "i'm in",
)


class DittoState(TypedDict):
    """LangGraph state schema for the Ditto matchmaking conversation graph.

    All nodes read from and write to this shared state dict.  The ``messages``
    field uses the ``add_messages`` reducer so new messages are *appended*
    automatically; every other field is replaced on update.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    phase: str
    user_persona: dict
    persona_pool: list[dict]
    user_preferences: list[str]
    rejection_reasons: list[str]
    shown_match_ids: list[str]
    current_match: dict | None
    accepted_match: dict | None
    current_round: int
    max_rounds: int
    llm_model: str
    embedding_model: str


# ── Routing helpers ────────────────────────────────────────────────────────────


def _last_user_content(state: DittoState) -> str:
    """Return the content of the most recent HumanMessage in state (lowercased)."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg.content.lower()
    return ""


def _is_acceptance(text: str) -> bool:
    """Return True if *text* contains any acceptance signal."""
    return any(signal in text for signal in _ACCEPTANCE_SIGNALS)


# ── Conditional edge functions ─────────────────────────────────────────────────


def route_after_collect_preferences(state: DittoState) -> str:
    """Conditional edge after collect_preferences_node.

    When the node decides preference collection is complete it sets
    ``phase = 'presenting_match'``.  In that case we chain directly into
    ``score_matches`` (which then chains to ``present_match``) within the same
    graph invocation, so the user never sees a turn where ``current_match`` is
    still ``None``.

    If preferences are still being gathered the phase remains
    ``'collecting_preferences'`` and we return ``END`` so the orchestrator can
    deliver Ditto's follow-up question and wait for the next user message.
    """
    if state.get("phase") == "presenting_match":
        return "score_matches"
    return END


def route_after_user_response(state: DittoState) -> str:
    """Conditional edge called after the Customer Bot responds.

    Reads ``state['phase']`` and the last user message to decide which Ditto
    node should handle this turn.
    """
    phase = state.get("phase", "")

    if phase == "greeting":
        return "greeting"

    if phase == "collecting_preferences":
        return "collect_preferences"

    if phase == "presenting_match":
        # Belt-and-suspenders guard: if score_matches hasn't run yet (e.g. due
        # to a stale phase value), route there now rather than falling through
        # to acceptance/rejection logic with a None current_match.
        if state.get("current_match") is None:
            return "score_matches"
        user_text = _last_user_content(state)
        if _is_acceptance(user_text):
            return "date_proposal"
        # Rejected
        if state["current_round"] < state["max_rounds"]:
            return "handle_rejection"
        return "completed"

    if phase == "post_date_feedback":
        return "collect_feedback"

    # Default — covers "completed" and any unknown phase
    return "completed"


def route_after_rejection(state: DittoState) -> str:
    """After handle_rejection_node, always re-score to find the next candidate."""
    return "score_matches"


def route_after_scoring(state: DittoState) -> str:
    """After score_matches_node: present the match or end the conversation.

    Two termination conditions are checked in priority order:

    1. **No candidates remaining** (``current_match is None``): the pool is
       exhausted or all candidates were filtered out.  Route to ``completed``
       (END) immediately — this check must come *before* the max-rounds check
       so that pool exhaustion at any round triggers a clean exit.

    2. **Max rounds exceeded** (``current_round >= max_rounds``): the user has
       seen the maximum number of matches.  Route to ``completed`` (END).

    3. **Normal case**: a match is available and rounds remain.  Route to
       ``present_match``.
    """
    # Guard 1: No match found (pool exhausted or all filtered out)
    if state.get("current_match") is None:
        return "completed"

    # Guard 2: Max rounds exceeded
    if state.get("current_round", 0) >= state.get("max_rounds", 6):
        return "completed"

    # Normal: present the match
    return "present_match"


# ── Graph factory ──────────────────────────────────────────────────────────────


def build_ditto_graph() -> CompiledStateGraph:
    """Construct and compile the Ditto matchmaking StateGraph.

    Graph topology
    --------------
    START ──(conditional: route_after_user_response)──► greeting
                                                      ► collect_preferences
                                                      ► score_matches  (belt-and-suspenders)
                                                      ► date_proposal
                                                      ► handle_rejection ──► score_matches
                                                      ► collect_feedback
                                                      ► END  (completed)

    collect_preferences ──(conditional: route_after_collect_preferences)──► score_matches
                                                                          ► END

    score_matches ──(conditional: route_after_scoring)──► present_match ──► END
                                                        ► END  (no candidates)

    All terminal nodes (greeting, present_match, date_proposal, collect_feedback)
    go directly to END so that each orchestrator invocation handles exactly one
    complete Ditto action.
    """
    # Import node functions here to avoid circular imports at module load time
    from src.ditto_bot.nodes import (  # noqa: PLC0415
        collect_feedback_node,
        collect_preferences_node,
        date_proposal_node,
        greeting_node,
        handle_rejection_node,
        present_match_node,
        score_matches_node,
    )

    builder = StateGraph(DittoState)

    # ── Register nodes ─────────────────────────────────────────────────────────
    builder.add_node("greeting", greeting_node)
    builder.add_node("collect_preferences", collect_preferences_node)
    builder.add_node("score_matches", score_matches_node)
    builder.add_node("present_match", present_match_node)
    builder.add_node("handle_rejection", handle_rejection_node)
    builder.add_node("date_proposal", date_proposal_node)
    builder.add_node("collect_feedback", collect_feedback_node)

    # ── Entry: conditional dispatch from START ─────────────────────────────────
    # The orchestrator sets state['phase'] before each invocation; the router
    # decides which node handles this Ditto turn.
    builder.add_conditional_edges(
        START,
        route_after_user_response,
        {
            "greeting": "greeting",
            "collect_preferences": "collect_preferences",
            "score_matches": "score_matches",
            "handle_rejection": "handle_rejection",
            "date_proposal": "date_proposal",
            "collect_feedback": "collect_feedback",
            "completed": END,
        },
    )

    # ── collect_preferences: conditional edge to score_matches or END ──────────
    # When collect_preferences_node sets phase='presenting_match', chain
    # directly into score_matches (→ present_match → END) within the same
    # invocation.  Otherwise return END and wait for the next user message.
    builder.add_conditional_edges(
        "collect_preferences",
        route_after_collect_preferences,
        {
            "score_matches": "score_matches",
            END: END,
        },
    )

    # ── Internal chain: rejection → re-score → present ────────────────────────
    builder.add_edge("handle_rejection", "score_matches")

    builder.add_conditional_edges(
        "score_matches",
        route_after_scoring,
        {
            "present_match": "present_match",
            "completed": END,
        },
    )

    # ── Terminal nodes → END ───────────────────────────────────────────────────
    builder.add_edge("greeting", END)
    builder.add_edge("present_match", END)
    builder.add_edge("date_proposal", END)
    builder.add_edge("collect_feedback", END)

    return builder.compile()
