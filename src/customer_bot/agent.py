"""Customer Bot — persona-driven user simulation agent."""

from __future__ import annotations

import random
import logging
from typing import Optional

from src import config
from src.llm.client import LLMClient, get_conversation_client
from src.customer_bot.prompts import (
    CUSTOMER_SYSTEM_PROMPT,
    NOISE_INJECTION_PROMPTS,
    GHOSTING_MESSAGES,
)
from src.models.persona import Persona, PreferenceStrictness, CommunicationStyle

logger = logging.getLogger(__name__)


class CustomerBot:
    """Persona-driven user bot that simulates realistic student interactions.
    
    Behaviors:
    - Responds naturally based on persona's communication style
    - Evaluates matches against persona's actual preferences
    - Injects noise (random questions, bug reports, off-topic chat)
    - Can ghost or drop off based on frustration/preference strictness
    - Provides post-date ratings calibrated to match quality
    
    Critical: This bot has NO access to Ditto Bot's internal scoring logic.
    All decisions are based on the persona's preferences and the match profile
    as presented in natural language.
    """

    def __init__(
        self,
        persona: Persona,
        llm_client: LLMClient | None = None,
    ):
        self.persona = persona
        self.client = llm_client or get_conversation_client()
        self.conversation_history: list[dict[str, str]] = []
        self.frustration_level: float = 0.0  # 0.0 (happy) to 1.0 (fed up)
        self.rounds_seen: int = 0
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build persona-conditioned system prompt."""
        prefs = self.persona.dating_preferences
        return CUSTOMER_SYSTEM_PROMPT.format(
            persona_profile=self.persona.to_profile_summary(),
            communication_style=self.persona.communication_style.value,
            preference_strictness=self.persona.preference_strictness.value,
            date_type=self.persona.date_type.value.replace("_", " "),
            preferred_genders=", ".join(g.value for g in prefs.preferred_genders),
            preferred_age_range=f"{prefs.preferred_age_min}-{prefs.preferred_age_max}",
            preferred_ethnicities=", ".join(prefs.preferred_ethnicities) if prefs.preferred_ethnicities else "no strong preference",
            physical_criteria=", ".join(prefs.physical_attraction_criteria) if prefs.physical_attraction_criteria else "no specific criteria",

        )

    def respond(self, ditto_message: str) -> str:
        """Generate a response to a Ditto Bot message.
        
        May inject noise, ghost, or respond normally based on persona and state.
        """
        # Check for ghosting
        if self._should_ghost():
            logger.info(f"  [{self.persona.name}] ghosting")
            return random.choice(GHOSTING_MESSAGES)

        # Check for noise injection (~10% chance)
        if random.random() < 0.10:
            noise = random.choice(NOISE_INJECTION_PROMPTS)
            logger.info(f"  [{self.persona.name}] injecting noise: {noise[:40]}...")
            return noise

        # Normal response
        self.conversation_history.append({"role": "user", "content": ditto_message})

        response = self.client.chat(
            messages=self.conversation_history,
            system_prompt=self._system_prompt,
            temperature=0.9,
        )

        self.conversation_history.append({"role": "assistant", "content": response})
        return response

    def evaluate_match(self, ditto_message: str) -> str:
        """Evaluate a match presented by Ditto and respond with accept/reject.
        
        Decision is based on the persona's preferences and the match description.
        The bot does NOT have access to any scoring data — only the natural-language
        match presentation from Ditto.
        """
        self.rounds_seen += 1

        prompt = (
            f"Ditto just presented you with a match. Here's what they said:\n\n"
            f'"{ditto_message}"\n\n'
            f"Based on YOUR preferences and personality, decide:\n"
            f"1. Are you interested in this person? Why or why not?\n"
            f"2. If not interested, what specifically doesn't work for you?\n\n"
            f"Respond naturally in your communication style. "
            f"Remember: you are {self.persona.preference_strictness.value} about your preferences.\n"
            f"This is match #{self.rounds_seen}. "
        )

        # Add frustration context
        if self.frustration_level > 0.5:
            prompt += (
                f"You're getting a bit frustrated with the matches so far. "
                f"Show some impatience but don't be rude."
            )

        if self.rounds_seen > 3:
            prompt += (
                f"You've seen {self.rounds_seen} matches now. You might be losing patience."
            )

        self.conversation_history.append({"role": "user", "content": prompt})

        response = self.client.chat(
            messages=self.conversation_history,
            system_prompt=self._system_prompt,
            temperature=0.9,
        )

        self.conversation_history.append({"role": "assistant", "content": response})

        # Update frustration based on whether this seems like a rejection
        lower = response.lower()
        is_rejection = any(w in lower for w in [
            "no", "not", "don't", "nah", "pass", "nope", "meh",
            "not really", "not my type", "not interested",
        ])
        if is_rejection:
            self.frustration_level = min(1.0, self.frustration_level + 0.2)
        else:
            self.frustration_level = max(0.0, self.frustration_level - 0.1)

        return response

    def give_post_date_feedback(self, ditto_message: str) -> tuple[str, int]:
        """Generate post-date feedback including a rating 1-5.
        
        Returns:
            Tuple of (feedback_message, rating)
        """
        prompt = (
            f"Ditto is asking about your date:\n\n"
            f'"{ditto_message}"\n\n'
            f"You went on the date. Think about whether the match actually worked "
            f"for you based on your personality and preferences.\n\n"
            f"In your response:\n"
            f"1. Share how the date went naturally\n"
            f"2. Mention specific things you liked or didn't like\n"
            f"3. Say whether you'd see them again\n"
            f"4. At the very end, rate the date from 1-5 like this: 'Rating: X/5'\n\n"
            f"Be honest and in character."
        )

        self.conversation_history.append({"role": "user", "content": prompt})

        response = self.client.chat(
            messages=self.conversation_history,
            system_prompt=self._system_prompt,
            temperature=0.8,
        )

        self.conversation_history.append({"role": "assistant", "content": response})

        # Extract rating
        rating = self._extract_rating(response)

        return response, rating

    def _extract_rating(self, text: str) -> int:
        """Extract a 1-5 rating from the response text."""
        import re
        # Look for patterns like "Rating: 4/5", "4/5", "4 out of 5"
        patterns = [
            r"[Rr]ating:\s*(\d)/5",
            r"(\d)/5",
            r"(\d)\s*out\s*of\s*5",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                rating = int(match.group(1))
                return max(1, min(5, rating))

        # Default: moderate rating based on overall tone
        lower = text.lower()
        if any(w in lower for w in ["amazing", "great", "loved", "awesome", "perfect"]):
            return 4
        elif any(w in lower for w in ["bad", "awful", "terrible", "worst", "boring"]):
            return 2
        return 3

    def _should_ghost(self) -> bool:
        """Determine if the user should ghost based on frustration and persona traits."""
        # Base ghosting probability
        base_prob = config.DROP_OFF_PROBABILITY

        # Higher for reserved/sarcastic styles
        if self.persona.communication_style in (
            CommunicationStyle.RESERVED,
            CommunicationStyle.SARCASTIC,
        ):
            base_prob *= 1.5

        # Higher with frustration
        ghost_prob = base_prob + (self.frustration_level * 0.2)

        # Higher after many rounds
        if self.rounds_seen > 3:
            ghost_prob += 0.1

        return random.random() < ghost_prob

    @property
    def has_dropped_off(self) -> bool:
        """Check if the last response was a ghost/drop-off."""
        if not self.conversation_history:
            return False
        last = self.conversation_history[-1].get("content", "")
        return last in GHOSTING_MESSAGES or len(last.strip()) <= 3
