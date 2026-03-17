"""Simulation engine — orchestrates multi-turn conversations between Ditto Bot and Customer Bot."""

from __future__ import annotations

import logging
import random
import time

from langchain_core.messages import AIMessage, HumanMessage

from src import config
from src.llm.client import LLMClient, get_llm_client
from src.ditto_bot.graph import build_ditto_graph, DittoState
from src.customer_bot.agent import CustomerBot
from src.orchestrator.logger import ConversationLogger
from src.models.persona import Persona
from src.models.conversation import (
    ConversationLog,
    Turn,
    TurnRole,
    MatchPresented,
    SentimentLabel,
)

logger = logging.getLogger(__name__)


class SimulationEngine:
    """Orchestrates conversation simulations between Ditto Bot and Customer Bot pairs.
    
    Manages:
    - Pairing personas from the pool for each conversation
    - Running the conversation loop with turn limits
    - Tracking sentiment trajectory
    - Drop-off simulation
    - Sequential execution
    - JSONL logging
    """

    def __init__(
        self,
        persona_pool: list[Persona],
        llm_client: LLMClient | None = None,
        output_dir=None,
        mongo_enabled: bool = False,
    ):
        self.persona_pool = persona_pool
        self.client = llm_client or get_llm_client()
        self.logger = ConversationLogger(output_dir=output_dir, mongo_enabled=mongo_enabled)
        # Build the compiled LangGraph once and reuse across conversations
        self._ditto_graph = build_ditto_graph()

    def run(
        self,
        num_conversations: int = config.DEFAULT_CONVERSATION_COUNT,
    ) -> list[ConversationLog]:
        """Run the simulation.

        Args:
            num_conversations: Number of conversations to simulate.

        Returns:
            List of completed ConversationLog entries.
        """
        logger.info(f"Starting simulation: {num_conversations} conversations")
        logger.info(f"Persona pool size: {len(self.persona_pool)}")
        logger.info(f"Max rounds per conversation: {config.MAX_MATCH_ROUNDS}")
        logger.info(f"Output: {self.logger.log_file_path}")

        # Select user personas for each conversation (with replacement if needed)
        user_personas = self._select_user_personas(num_conversations)

        results = []
        start_time = time.time()

        for i, persona in enumerate(user_personas):
            logger.info(f"\n{'='*60}")
            logger.info(f"Conversation {i+1}/{num_conversations}: {persona.name}")
            logger.info(f"{'='*60}")

            try:
                log = self._run_single_conversation(persona)
                results.append(log)
                self.logger.log_conversation(log)

                # Progress summary
                accepted = "✅" if log.rounds_to_acceptance else "❌"
                rating = f"⭐{log.post_date_rating}" if log.post_date_rating else "N/A"
                dropped = "👻" if log.dropped_off else ""
                logger.info(
                    f"  Result: {accepted} rounds={log.total_rounds} "
                    f"rating={rating} {dropped}"
                )

            except Exception as e:
                logger.error(f"  Conversation {i+1} failed: {e}")
                # Partial log is saved inside _run_single_conversation before re-raising
                continue

        elapsed = time.time() - start_time
        logger.info(f"\n{'='*60}")
        logger.info(f"Simulation complete: {len(results)}/{num_conversations} conversations")
        logger.info(f"Time elapsed: {elapsed:.1f}s ({elapsed/max(len(results),1):.1f}s avg)")
        logger.info(f"Output file: {self.logger.log_file_path}")
        self._print_summary(results)

        return results

    def _run_single_conversation(self, user_persona: Persona) -> ConversationLog:
        """Run a single conversation between Ditto Bot (LangGraph) and a Customer Bot."""

        # Initialize CustomerBot — uses the raw LLMClient (unchanged)
        customer = CustomerBot(
            persona=user_persona,
            llm_client=self.client,
        )

        # Initialize log
        log = ConversationLog(persona=user_persona)
        turns: list[Turn] = []
        sentiment_trajectory: list[SentimentLabel] = [SentimentLabel.NEUTRAL]

        # ── Build initial DittoState ───────────────────────────────────────────
        state: DittoState = {
            "messages": [],
            "user_persona": user_persona.model_dump(),
            "persona_pool": [p.model_dump() for p in self.persona_pool],
            "phase": "greeting",
            "user_preferences": [],
            "rejection_reasons": [],
            "shown_match_ids": [],
            "current_match": None,
            "accepted_match": None,
            "current_round": 0,
            "max_rounds": config.MAX_MATCH_ROUNDS,
            "llm_model": self.client.model,
            "embedding_model": self.client.embedding_model,
        }

        try:
            # ── Phase 1: Invoke graph to get the greeting ─────────────────────────
            state = self._ditto_graph.invoke(state)

            # Extract the AI greeting from the last message
            greeting = self._extract_last_ai_message(state)
            turns.append(Turn(role=TurnRole.DITTO, content=greeting))
            logger.info(f"  [Ditto] {greeting[:100]}...")

            # ── Phase 2: Customer responds to greeting ────────────────────────────
            user_response = customer.respond(greeting)
            turns.append(Turn(role=TurnRole.USER, content=user_response))
            logger.info(f"  [{user_persona.name}] {user_response[:100]}...")

            # Check for immediate drop-off
            if customer.has_dropped_off:
                log.dropped_off = True
                log.turns = turns
                log.sentiment_trajectory = sentiment_trajectory
                return log

            # ── Phase 3: Main conversation loop ───────────────────────────────────
            turn_count = 0
            max_turns = config.MAX_CONVERSATION_TURNS

            while turn_count < max_turns:
                turn_count += 1

                # Add the latest user message to state and invoke the graph
                state["messages"] = list(state["messages"]) + [HumanMessage(content=user_response)]
                state = self._ditto_graph.invoke(state)

                # Extract Ditto's response
                ditto_response = self._extract_last_ai_message(state)
                turns.append(Turn(role=TurnRole.DITTO, content=ditto_response))
                logger.info(f"  [Ditto] {ditto_response[:100]}...")

                current_phase = state.get("phase", "completed")

                # Check for conversation completion
                if current_phase == "completed":
                    break

                # ── Phase-specific customer response logic ────────────────────────
                if current_phase == "presenting_match":
                    # Record the match presented
                    current_match = state.get("current_match")
                    if current_match:
                        match_candidate = current_match.get("candidate", {})
                        match_presented = MatchPresented(
                            match_id=match_candidate.get("id", ""),
                            match_name=match_candidate.get("name", "Unknown"),
                            round=state.get("current_round", 1),
                            accepted=False,  # Will update if accepted
                            justification=current_match.get("justification", ""),
                        )
                        log.matches_presented.append(match_presented)

                    # Customer evaluates the match
                    user_response = customer.evaluate_match(ditto_response)
                    turns.append(Turn(role=TurnRole.USER, content=user_response))
                    logger.info(f"  [{user_persona.name}] {user_response[:100]}...")

                    # Check if accepted
                    lower = user_response.lower()
                    accepted = any(w in lower for w in [
                        "yes", "sure", "sounds good", "let's do it", "okay", "down",
                        "interested", "love", "great", "accept", "cool",
                    ])

                    if accepted and log.matches_presented:
                        log.matches_presented[-1].accepted = True
                        log.rounds_to_acceptance = state.get("current_round", 1)
                        sentiment_trajectory.append(SentimentLabel.EXCITED)
                    else:
                        log.rejection_reasons.append(user_response)
                        sentiment_trajectory.append(
                            SentimentLabel.FRUSTRATED if customer.frustration_level > 0.4
                            else SentimentLabel.NEUTRAL
                        )

                elif current_phase == "post_date_feedback":
                    # Customer gives post-date feedback
                    feedback_response, rating = customer.give_post_date_feedback(ditto_response)
                    turns.append(Turn(role=TurnRole.USER, content=feedback_response))
                    logger.info(f"  [{user_persona.name}] {feedback_response[:100]}... (Rating: {rating})")

                    log.post_date_rating = rating
                    log.post_date_feedback = feedback_response
                    user_response = feedback_response
                    sentiment_trajectory.append(
                        SentimentLabel.SATISFIED if rating >= 3 else SentimentLabel.DISAPPOINTED
                    )

                else:
                    # General response (collecting_preferences or other phases)
                    user_response = customer.respond(ditto_response)
                    turns.append(Turn(role=TurnRole.USER, content=user_response))
                    logger.info(f"  [{user_persona.name}] {user_response[:100]}...")

                # Check for drop-off
                if customer.has_dropped_off:
                    log.dropped_off = True
                    sentiment_trajectory.append(SentimentLabel.FRUSTRATED)
                    logger.info(f"  [{user_persona.name}] 👻 dropped off")
                    break

            # ── Finalize log ──────────────────────────────────────────────────────
            log.turns = turns
            log.sentiment_trajectory = sentiment_trajectory
            log.total_rounds = state.get("current_round", 0)

            return log

        except Exception as e:
            # Save whatever turns were collected before the crash
            if turns:
                partial_log = ConversationLog(
                    persona=user_persona,
                    turns=turns,
                    matches_presented=log.matches_presented,
                    rejection_reasons=log.rejection_reasons,
                    sentiment_trajectory=sentiment_trajectory,
                    rounds_to_acceptance=log.rounds_to_acceptance,
                    post_date_rating=log.post_date_rating,
                    post_date_feedback=log.post_date_feedback,
                    dropped_off=True,
                    total_rounds=state.get("current_round", 0),
                )
                self.logger.log_conversation(partial_log)
                logger.info(f"Saved partial conversation ({len(turns)} turns) despite error")
            # Re-raise so the caller's except block can count this as a failure
            raise

    def _extract_last_ai_message(self, state: DittoState) -> str:
        """Extract the content of the most recent AIMessage from graph state."""
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg.content
        return ""

    def _select_user_personas(self, count: int) -> list[Persona]:
        """Select user personas for conversations, sampling with replacement if needed."""
        if count <= len(self.persona_pool):
            return random.sample(self.persona_pool, count)
        else:
            return random.choices(self.persona_pool, k=count)

    def _print_summary(self, results: list[ConversationLog]):
        """Print a summary of the simulation results."""
        if not results:
            logger.info("No results to summarize.")
            return

        total = len(results)
        accepted = sum(1 for r in results if r.rounds_to_acceptance is not None)
        dropped = sum(1 for r in results if r.dropped_off)
        ratings = [r.post_date_rating for r in results if r.post_date_rating is not None]
        rounds = [r.total_rounds for r in results]

        logger.info(f"\n📊 SIMULATION SUMMARY")
        logger.info(f"  Total conversations: {total}")
        logger.info(f"  Matches accepted: {accepted} ({accepted/total:.0%})")
        logger.info(f"  Drop-offs: {dropped} ({dropped/total:.0%})")
        logger.info(f"  Avg rounds: {sum(rounds)/len(rounds):.1f}")
        if ratings:
            logger.info(f"  Avg post-date rating: {sum(ratings)/len(ratings):.1f}/5")
        if accepted:
            acceptance_rounds = [
                r.rounds_to_acceptance for r in results
                if r.rounds_to_acceptance is not None
            ]
            logger.info(f"  Avg rounds to acceptance: {sum(acceptance_rounds)/len(acceptance_rounds):.1f}")
