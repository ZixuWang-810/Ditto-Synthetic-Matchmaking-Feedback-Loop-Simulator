"""LangGraph node functions replicating DittoBot's phase logic.

Each node takes a ``DittoState`` and returns a partial state dict update.
All LLM calls use the raw ``LLMClient`` (not ChatOllama) and wrap responses
in ``AIMessage`` for LangGraph state compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src import config
from src.ditto_bot.graph import DittoState
from src.ditto_bot.matcher import MatchScorer
from src.ditto_bot.prompts import (
    DATE_PROPOSAL_PROMPT,
    DITTO_SYSTEM_PROMPT,
    MATCH_PRESENTATION_PROMPT,
    POST_DATE_FEEDBACK_PROMPT,
    REJECTION_HANDLING_PROMPT,
)
from src.llm.client import LLMClient
from src.models.persona import Persona

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_client(state: DittoState) -> LLMClient:
    """Instantiate an LLMClient using the model stored in state."""
    return LLMClient(model=state["llm_model"], embedding_model=state["embedding_model"])


def _persona_from_dict(d: dict) -> Persona:
    """Reconstruct a Persona from a plain dict (as stored in state)."""
    return Persona.model_validate(d)


def _messages_to_history(messages) -> list[dict[str, str]]:
    """Convert LangChain message objects to the plain-dict format expected by LLMClient."""
    history: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            history.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            history.append({"role": "assistant", "content": msg.content})
        else:
            # SystemMessage or other — skip; system prompt is passed separately
            pass
    return history


def _last_user_message(state: DittoState) -> str:
    """Return the content of the most recent HumanMessage in state."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


# ── Node 1: Greeting ──────────────────────────────────────────────────────────


def greeting_node(state: DittoState) -> dict[str, Any]:
    """Generate the opening greeting and transition to collecting_preferences.

    Mirrors ``DittoBot.start_conversation`` (agent.py lines ~72-95).
    """
    client = _make_client(state)
    user_persona = _persona_from_dict(state["user_persona"])

    system_prompt = DITTO_SYSTEM_PROMPT.format(max_rounds=state["max_rounds"])

    greeting_prompt = (
        f"You are starting a conversation with a new student. "
        f"Their name is {user_persona.name}. "
        f"They are a {user_persona.degree_level.value} at {user_persona.university}. "
        f"Greet them warmly and ask what kind of connection they're looking for and "
        f"what matters to them in a date. Be brief and natural."
    )

    response = client.chat(
        messages=[{"role": "user", "content": greeting_prompt}],
        system_prompt=system_prompt,
    )

    logger.debug("greeting_node: generated greeting for %s", user_persona.name)

    return {
        "messages": [AIMessage(content=response)],
        "phase": "collecting_preferences",
    }


# ── Node 2: Collect Preferences ───────────────────────────────────────────────


def collect_preferences_node(state: DittoState) -> dict[str, Any]:
    """Collect user preferences and respond conversationally.

    Mirrors ``DittoBot._handle_preference_collection`` (agent.py lines ~121-171).
    Appends the latest user message to ``user_preferences``.
    Transitions to ``'presenting_match'`` once at least 2 user messages have
    been exchanged; otherwise stays at ``'collecting_preferences'``.
    """
    client = _make_client(state)
    system_prompt = DITTO_SYSTEM_PROMPT.format(max_rounds=state["max_rounds"])

    user_message = _last_user_message(state)

    # Accumulate preferences
    updated_preferences = state["user_preferences"] + [user_message]

    # Count how many HumanMessages are in the conversation so far
    human_turn_count = sum(1 for m in state["messages"] if isinstance(m, HumanMessage))

    # Build conversation history for the LLM
    history = _messages_to_history(state["messages"])

    # Ask the LLM to respond conversationally and extract preference info
    context_message = (
        f"The student said: \"{user_message}\"\n\n"
        f"Respond naturally, acknowledge what they're looking for, and ask a "
        f"follow-up question to learn more about their preferences if needed. "
        f"Keep it conversational and brief."
    )

    # Replace the last user entry with the enriched context message for the LLM
    llm_history = history[:-1] + [{"role": "user", "content": context_message}]

    response = client.chat(
        messages=llm_history,
        system_prompt=system_prompt,
    )

    # Transition to presenting_match after at least 2 user turns
    next_phase = "presenting_match" if human_turn_count >= 2 else "collecting_preferences"

    logger.debug(
        "collect_preferences_node: human_turns=%d, next_phase=%s",
        human_turn_count,
        next_phase,
    )

    return {
        "messages": [AIMessage(content=response)],
        "user_preferences": updated_preferences,
        "phase": next_phase,
    }


# ── Node 3: Score Matches ─────────────────────────────────────────────────────


def score_matches_node(state: DittoState) -> dict[str, Any]:
    """Score and rank candidates; select the top result.

    Pure computation node — no conversational LLM call.
    Mirrors the scoring logic used in ``DittoBot._handle_preference_collection``.
    """
    client = _make_client(state)
    scorer = MatchScorer(llm_client=client)

    user_persona = _persona_from_dict(state["user_persona"])
    candidates = [_persona_from_dict(d) for d in state["persona_pool"]]

    shown_ids: set[str] = set(state["shown_match_ids"])

    results = scorer.score_candidates(
        user=user_persona,
        candidates=candidates,
        rejection_reasons=state["rejection_reasons"],
        shown_ids=shown_ids,
    )

    if not results:
        logger.info("No eligible candidates remaining — ending conversation")
        return {
            "messages": [AIMessage(content=(
                "I've gone through all my available matches for you. "
                "Let's wrap up for now — check back soon for new people!"
            ))],
            "current_match": None,
            "phase": "completed",
        }

    best = results[0]
    new_shown = state["shown_match_ids"] + [best.candidate.id]

    logger.debug(
        "score_matches_node: best match=%s (score=%.2f)",
        best.candidate.name,
        best.combined_score,
    )

    return {
        "current_match": best.model_dump(),
        "current_round": state["current_round"] + 1,
        "shown_match_ids": new_shown,
    }


# ── Node 4: Present Match ─────────────────────────────────────────────────────


def present_match_node(state: DittoState) -> dict[str, Any]:
    """Format and present the current match to the user.

    Mirrors ``DittoBot._handle_preference_collection`` match-presentation block
    (agent.py lines ~145-171) and ``DittoBot._present_match`` pattern.
    """
    client = _make_client(state)
    system_prompt = DITTO_SYSTEM_PROMPT.format(max_rounds=state["max_rounds"])

    user_persona = _persona_from_dict(state["user_persona"])

    current_match = state.get("current_match")
    if current_match is None:
        # No match available — inform the user gracefully
        response = (
            "I'm so sorry, but I've gone through all viable matches for you right now. "
            "Check back soon — new people are joining Ditto every day! 🙏"
        )
        return {
            "messages": [AIMessage(content=response)],
            "phase": "completed",
        }

    # Reconstruct the match candidate Persona from the stored dict
    match_candidate = _persona_from_dict(current_match["candidate"])
    combined_score: float = current_match.get("combined_score", 0.0)

    presentation_prompt = MATCH_PRESENTATION_PROMPT.format(
        user_profile=user_persona.to_profile_summary(),
        user_preferences="; ".join(state["user_preferences"]) or "No preferences stated yet",
        rejection_history=(
            "; ".join(state["rejection_reasons"]) if state["rejection_reasons"] else "None yet"
        ),
        match_profile=match_candidate.to_profile_summary(),
        compatibility_score=combined_score,
    )

    context_message = (
        f"You found a match for the student. Present this match naturally:\n\n"
        f"{presentation_prompt}\n\n"
        f"After presenting the match, ask if they'd like to meet this person. "
        f"This is match round {state['current_round']} of {state['max_rounds']}."
    )

    history = _messages_to_history(state["messages"])
    history.append({"role": "user", "content": context_message})

    response = client.chat(
        messages=history,
        system_prompt=system_prompt,
    )

    logger.debug("present_match_node: presented %s", match_candidate.name)

    return {
        "messages": [AIMessage(content=response)],
        "phase": "presenting_match",
    }


# ── Node 5: Handle Rejection ──────────────────────────────────────────────────


def handle_rejection_node(state: DittoState) -> dict[str, Any]:
    """Acknowledge the rejection, extract the reason, and prepare for the next match.

    Mirrors ``DittoBot._handle_match_response`` rejection branch and
    ``DittoBot._handle_rejection_feedback`` (agent.py lines ~173-237).
    """
    client = _make_client(state)
    system_prompt = DITTO_SYSTEM_PROMPT.format(max_rounds=state["max_rounds"])

    user_message = _last_user_message(state)

    rejection_prompt = REJECTION_HANDLING_PROMPT.format(
        rejection_message=user_message,
        rejection_history=(
            "; ".join(state["rejection_reasons"]) if state["rejection_reasons"] else "None yet"
        ),
    )

    context_message = (
        f"The student rejected the match. They said: \"{user_message}\"\n\n"
        f"{rejection_prompt}"
    )

    history = _messages_to_history(state["messages"])
    history.append({"role": "user", "content": context_message})

    response = client.chat(
        messages=history,
        system_prompt=system_prompt,
    )

    # Use the user's raw message as the extracted rejection reason
    extracted_reason = user_message

    updated_rejection_reasons = state["rejection_reasons"] + [extracted_reason]

    logger.debug(
        "handle_rejection_node: recorded rejection reason: %s", extracted_reason
    )

    return {
        "messages": [AIMessage(content=response)],
        "rejection_reasons": updated_rejection_reasons,
        "phase": "presenting_match",
    }


# ── Node 6: Date Proposal ─────────────────────────────────────────────────────


def date_proposal_node(state: DittoState) -> dict[str, Any]:
    """Propose a date for the accepted match.

    Mirrors ``DittoBot._handle_match_response`` acceptance branch (agent.py ~185-202).
    """
    client = _make_client(state)
    system_prompt = DITTO_SYSTEM_PROMPT.format(max_rounds=state["max_rounds"])

    user_persona = _persona_from_dict(state["user_persona"])

    current_match = state.get("current_match")
    if current_match is None:
        logger.error("date_proposal_node: current_match is None — cannot propose date")
        return {
            "messages": [AIMessage(content="Something went wrong — I couldn't find your match details. Let me try again!")],
            "phase": "presenting_match",
        }

    match_candidate = _persona_from_dict(current_match["candidate"])
    shared_interests: list[str] = current_match.get("shared_interests", [])

    date_prompt = DATE_PROPOSAL_PROMPT.format(
        user_profile=user_persona.to_profile_summary(),
        match_profile=match_candidate.to_profile_summary(),
        shared_interests=", ".join(shared_interests) if shared_interests else "various interests",
    )

    user_message = _last_user_message(state)
    context_message = (
        f"The student accepted the match! They said: \"{user_message}\"\n\n"
        f"{date_prompt}"
    )

    history = _messages_to_history(state["messages"])
    history.append({"role": "user", "content": context_message})

    response = client.chat(
        messages=history,
        system_prompt=system_prompt,
    )

    logger.debug("date_proposal_node: proposed date with %s", match_candidate.name)

    return {
        "messages": [AIMessage(content=response)],
        "phase": "post_date_feedback",
        "accepted_match": state["current_match"],
    }


# ── Node 7: Collect Feedback ──────────────────────────────────────────────────


def collect_feedback_node(state: DittoState) -> dict[str, Any]:
    """Ask for post-date feedback and mark the conversation as completed.

    Mirrors ``DittoBot._handle_date_response`` (agent.py lines ~239-255).
    """
    client = _make_client(state)
    system_prompt = DITTO_SYSTEM_PROMPT.format(max_rounds=state["max_rounds"])

    user_message = _last_user_message(state)

    context_message = (
        f"The student responded to the date proposal: \"{user_message}\"\n\n"
        f"[SIMULATION NOTE: The date has now happened.]\n\n"
        f"{POST_DATE_FEEDBACK_PROMPT}"
    )

    history = _messages_to_history(state["messages"])
    history.append({"role": "user", "content": context_message})

    response = client.chat(
        messages=history,
        system_prompt=system_prompt,
    )

    logger.debug("collect_feedback_node: requested post-date feedback")

    return {
        "messages": [AIMessage(content=response)],
        "phase": "completed",
    }
