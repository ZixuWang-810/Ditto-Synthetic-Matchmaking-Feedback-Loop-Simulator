"""Ditto Bot — stateful matchmaking conversational agent."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from src import config
from src.llm.client import LLMClient, get_llm_client
from src.ditto_bot.matcher import MatchScorer, MatchResult
from src.ditto_bot.prompts import (
    DITTO_SYSTEM_PROMPT,
    MATCH_PRESENTATION_PROMPT,
    REJECTION_HANDLING_PROMPT,
    DATE_PROPOSAL_PROMPT,
    POST_DATE_FEEDBACK_PROMPT,
)
from src.models.persona import Persona

logger = logging.getLogger(__name__)


class ConversationPhase(str, Enum):
    """Tracks the current phase of the matchmaking conversation."""
    GREETING = "greeting"
    COLLECTING_PREFERENCES = "collecting_preferences"
    PRESENTING_MATCH = "presenting_match"
    HANDLING_REJECTION = "handling_rejection"
    DATE_PROPOSAL = "date_proposal"
    POST_DATE_FEEDBACK = "post_date_feedback"
    COMPLETED = "completed"


class DittoBot:
    """Stateful Ditto matchmaking bot that manages the full conversation flow.
    
    Uses Ollama local models for conversation generation, match scoring,
    and embeddings.
    
    State Management:
    - Tracks conversation phase
    - Remembers all preference statements and rejection reasons
    - Maintains history of shown matches
    - Limits to MAX_MATCH_ROUNDS attempts
    """

    def __init__(
        self,
        persona_pool: list[Persona],
        llm_client: LLMClient | None = None,
    ):
        self.persona_pool = persona_pool
        self.client = llm_client or get_llm_client()
        self.scorer = MatchScorer(llm_client=self.client)

        # State
        self.phase = ConversationPhase.GREETING
        self.current_round: int = 0
        self.user_preferences: list[str] = []
        self.rejection_reasons: list[str] = []
        self.shown_match_ids: set[str] = set()
        self.current_match: Optional[MatchResult] = None
        self.accepted_match: Optional[MatchResult] = None
        self.conversation_history: list[dict[str, str]] = []
        self._user_persona: Optional[Persona] = None

    def start_conversation(self, user_persona: Persona) -> str:
        """Initialize a new conversation with a user persona. Returns the greeting."""
        self._user_persona = user_persona
        self.phase = ConversationPhase.GREETING

        system_prompt = DITTO_SYSTEM_PROMPT.format(
            max_rounds=config.MAX_MATCH_ROUNDS
        )

        greeting_prompt = (
            f"You are starting a conversation with a new student. Their name is {user_persona.name}. "
            f"They are a {user_persona.degree_level.value} at {user_persona.university}. "
            f"Greet them warmly and ask what kind of connection they're looking for and "
            f"what matters to them in a date. Be brief and natural."
        )

        response = self.client.chat(
            messages=[{"role": "user", "content": greeting_prompt}],
            system_prompt=system_prompt,
        )

        self.conversation_history.append({"role": "user", "content": greeting_prompt})
        self.conversation_history.append({"role": "assistant", "content": response})
        self.phase = ConversationPhase.COLLECTING_PREFERENCES

        return response

    def respond(self, user_message: str) -> str:
        """Process a user message and return the Ditto bot's response.
        
        The response depends on the current conversation phase and automatically
        advances the phase based on the conversation state.
        """
        if self._user_persona is None:
            raise RuntimeError("Call start_conversation() first")

        system_prompt = DITTO_SYSTEM_PROMPT.format(
            max_rounds=config.MAX_MATCH_ROUNDS
        )

        if self.phase == ConversationPhase.COLLECTING_PREFERENCES:
            return self._handle_preference_collection(user_message, system_prompt)
        elif self.phase == ConversationPhase.PRESENTING_MATCH:
            return self._handle_match_response(user_message, system_prompt)
        elif self.phase == ConversationPhase.HANDLING_REJECTION:
            return self._handle_rejection_feedback(user_message, system_prompt)
        elif self.phase == ConversationPhase.DATE_PROPOSAL:
            return self._handle_date_response(user_message, system_prompt)
        elif self.phase == ConversationPhase.POST_DATE_FEEDBACK:
            return self._handle_post_date(user_message, system_prompt)
        else:
            return "Thanks for using Ditto! Hope we helped you find a great match 💛"

    def _handle_preference_collection(self, user_message: str, system_prompt: str) -> str:
        """Collect preferences, then find and present a match."""
        self.user_preferences.append(user_message)

        # After the user shares preferences, find a match
        match_result = self.scorer.get_best_match(
            user=self._user_persona,
            candidates=self.persona_pool,
            rejection_reasons=self.rejection_reasons,
            shown_ids=self.shown_match_ids,
        )

        if match_result is None:
            self.phase = ConversationPhase.COMPLETED
            return (
                "I'm so sorry, but I've gone through all viable matches for you right now. "
                "Check back soon — new people are joining Ditto every day! 🙏"
            )

        self.current_match = match_result
        self.current_round += 1
        self.shown_match_ids.add(match_result.candidate.id)

        # Generate match presentation
        presentation_prompt = MATCH_PRESENTATION_PROMPT.format(
            user_profile=self._user_persona.to_profile_summary(),
            user_preferences="; ".join(self.user_preferences),
            rejection_history="; ".join(self.rejection_reasons) if self.rejection_reasons else "None yet",
            match_profile=match_result.candidate.to_profile_summary(),
            compatibility_score=match_result.combined_score,
        )

        context_message = (
            f"The student shared their preferences: \"{user_message}\"\n\n"
            f"You found a match for them. Present this match naturally:\n\n"
            f"{presentation_prompt}\n\n"
            f"After presenting the match, ask if they'd like to meet this person. "
            f"This is match round {self.current_round} of {config.MAX_MATCH_ROUNDS}."
        )

        self.conversation_history.append({"role": "user", "content": context_message})

        response = self.client.chat(
            messages=self.conversation_history,
            system_prompt=system_prompt,
        )

        self.conversation_history.append({"role": "assistant", "content": response})
        self.phase = ConversationPhase.PRESENTING_MATCH

        return response

    def _handle_match_response(self, user_message: str, system_prompt: str) -> str:
        """Handle user's accept/reject of a presented match."""
        lower = user_message.lower()
        accepted = any(w in lower for w in [
            "yes", "sure", "sounds good", "let's do it", "okay", "down",
            "interested", "match", "love", "great", "accept", "cool",
        ])

        if accepted:
            self.accepted_match = self.current_match
            self.phase = ConversationPhase.DATE_PROPOSAL

            date_prompt = DATE_PROPOSAL_PROMPT.format(
                user_profile=self._user_persona.to_profile_summary(),
                match_profile=self.current_match.candidate.to_profile_summary(),
                shared_interests=", ".join(self.current_match.shared_interests) or "various",
            )

            context_message = (
                f"The student accepted the match! They said: \"{user_message}\"\n\n"
                f"{date_prompt}"
            )

            self.conversation_history.append({"role": "user", "content": context_message})
            response = self.client.chat(
                messages=self.conversation_history,
                system_prompt=system_prompt,
            )
            self.conversation_history.append({"role": "assistant", "content": response})
            return response
        else:
            # Rejected
            self.phase = ConversationPhase.HANDLING_REJECTION

            context_message = (
                f"The student rejected the match. They said: \"{user_message}\"\n\n"
                f"{REJECTION_HANDLING_PROMPT.format(rejection_message=user_message, rejection_history='; '.join(self.rejection_reasons) if self.rejection_reasons else 'None yet')}"
            )

            self.conversation_history.append({"role": "user", "content": context_message})
            response = self.client.chat(
                messages=self.conversation_history,
                system_prompt=system_prompt,
            )
            self.conversation_history.append({"role": "assistant", "content": response})
            return response

    def _handle_rejection_feedback(self, user_message: str, system_prompt: str) -> str:
        """Process rejection feedback, then present next match."""
        self.rejection_reasons.append(user_message)

        if self.current_round >= config.MAX_MATCH_ROUNDS:
            self.phase = ConversationPhase.COMPLETED
            return (
                "I appreciate your patience! We've gone through our rounds for today. "
                "I'll keep your preferences on file and find you better matches soon. "
                "Thanks for giving Ditto a shot! 💛"
            )

        # Find next match incorporating all rejection feedback
        self.phase = ConversationPhase.COLLECTING_PREFERENCES
        return self._handle_preference_collection(
            f"(Incorporating feedback: {user_message})",
            system_prompt,
        )

    def _handle_date_response(self, user_message: str, system_prompt: str) -> str:
        """Handle response to date proposal, then move to post-date feedback."""
        self.phase = ConversationPhase.POST_DATE_FEEDBACK

        context_message = (
            f"The student responded to the date proposal: \"{user_message}\"\n\n"
            f"[SIMULATION NOTE: The date has now happened.]\n\n"
            f"{POST_DATE_FEEDBACK_PROMPT}"
        )

        self.conversation_history.append({"role": "user", "content": context_message})
        response = self.client.chat(
            messages=self.conversation_history,
            system_prompt=system_prompt,
        )
        self.conversation_history.append({"role": "assistant", "content": response})
        return response

    def _handle_post_date(self, user_message: str, system_prompt: str) -> str:
        """Handle post-date feedback and wrap up."""
        self.phase = ConversationPhase.COMPLETED

        context_message = (
            f"The student gave post-date feedback: \"{user_message}\"\n\n"
            f"Thank them warmly and close out the conversation. "
            f"If they had a great time, be happy for them. If it wasn't great, "
            f"be empathetic and offer to find better matches next time."
        )

        self.conversation_history.append({"role": "user", "content": context_message})
        response = self.client.chat(
            messages=self.conversation_history,
            system_prompt=system_prompt,
        )
        self.conversation_history.append({"role": "assistant", "content": response})
        return response

    @property
    def is_complete(self) -> bool:
        """Whether the conversation has reached a terminal state."""
        return self.phase == ConversationPhase.COMPLETED
