"""Match scoring engine: embedding cosine similarity + LLM compatibility reasoning."""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from src import config
from src.llm.client import LLMClient, get_structured_client
from src.models.persona import Persona

logger = logging.getLogger(__name__)


class CompatibilityScore(BaseModel):
    """Structured LLM output for compatibility assessment."""
    score: float = Field(ge=0.0, le=1.0, description="Compatibility score 0-1")
    justification: str = Field(description="Why these two people are/aren't compatible")
    shared_interests: list[str] = Field(default_factory=list)
    potential_issues: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    """Result of matching a candidate against a user."""
    candidate: Persona
    embedding_score: float = Field(ge=0.0, le=1.0)
    llm_score: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)
    justification: str
    shared_interests: list[str] = Field(default_factory=list)


class MatchScorer:
    """Hybrid match scoring using embedding similarity and LLM reasoning.
    
    The scorer combines two signals:
    - Embedding cosine similarity (40% weight): Fast, semantic overlap of profiles
    - LLM compatibility reasoning (60% weight): Deep reasoning about personality,
      preferences, and overall compatibility
    
    This mirrors how real matchmaking systems blend fast retrieval with deep scoring.
    When the embedding model is unavailable, the scorer gracefully falls back to
    100% LLM-based scoring so conversations are never interrupted.
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.client = llm_client or get_structured_client()
        self._embedding_cache: dict[str, list[float]] = {}

    def score_candidates(
        self,
        user: Persona,
        candidates: list[Persona],
        rejection_reasons: list[str] | None = None,
        shown_ids: set[str] | None = None,
    ) -> list[MatchResult]:
        """Score and rank all candidates for a user.

        Args:
            user: The user seeking a match.
            candidates: Pool of potential matches.
            rejection_reasons: Previous rejection reasons to incorporate.
            shown_ids: IDs of already-shown matches to exclude.

        Returns:
            Sorted list of MatchResults, best match first.
        """
        shown_ids = shown_ids or set()
        rejection_reasons = rejection_reasons or []

        # Filter: remove shown matches and apply hard preference filters
        eligible = [
            c for c in candidates
            if c.id != user.id
            and c.id not in shown_ids
            and self._passes_hard_filters(user, c)
        ]

        if not eligible:
            logger.warning(f"No eligible candidates for {user.name} after filtering")
            return []

        # Stage 1: Embedding similarity (batch) — with graceful fallback
        # _warned_embedding_failure ensures the warning is logged only once per call
        _warned_embedding_failure = False
        embedding_scores, embedding_available = self._compute_embedding_scores_safe(
            user, eligible
        )

        if not embedding_available and not _warned_embedding_failure:
            logger.warning(
                "Embedding scoring failed, falling back to LLM-only: "
                "nomic-embed-text may not be pulled. "
                "All candidates will be scored using LLM reasoning only."
            )
            _warned_embedding_failure = True

        # Stage 2: LLM scoring for top candidates (cost optimization — only score top 5 by embedding)
        top_by_embedding = sorted(
            zip(eligible, embedding_scores),
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        results = []
        for candidate, emb_score in top_by_embedding:
            llm_result = self._llm_compatibility_score(
                user, candidate, rejection_reasons
            )

            if embedding_available:
                combined = (
                    config.EMBEDDING_SCORE_WEIGHT * emb_score
                    + config.LLM_SCORE_WEIGHT * llm_result.score
                )
            else:
                # Embeddings unavailable — use 100% LLM weight to avoid
                # artificially deflating scores (0.4 * 0 + 0.6 * llm = only 60%)
                combined = llm_result.score

            results.append(MatchResult(
                candidate=candidate,
                embedding_score=emb_score,
                llm_score=llm_result.score,
                combined_score=combined,
                justification=llm_result.justification,
                shared_interests=llm_result.shared_interests,
            ))

        results.sort(key=lambda r: r.combined_score, reverse=True)
        return results

    def get_best_match(
        self,
        user: Persona,
        candidates: list[Persona],
        rejection_reasons: list[str] | None = None,
        shown_ids: set[str] | None = None,
    ) -> Optional[MatchResult]:
        """Get the single best match for a user."""
        results = self.score_candidates(user, candidates, rejection_reasons, shown_ids)
        return results[0] if results else None

    def _passes_hard_filters(self, user: Persona, candidate: Persona) -> bool:
        """Check if a candidate passes the user's hard preference filters."""
        prefs = user.dating_preferences

        # Gender preference filter
        if prefs.preferred_genders and candidate.gender not in prefs.preferred_genders:
            return False

        # Age range filter
        if candidate.age < prefs.preferred_age_min or candidate.age > prefs.preferred_age_max:
            return False


        return True

    def _compute_embedding_scores_safe(
        self, user: Persona, candidates: list[Persona]
    ) -> tuple[list[float], bool]:
        """Compute embedding cosine similarity with graceful fallback.

        Returns:
            A tuple of (scores, embedding_available) where:
            - scores: per-candidate similarity scores (all 0.0 if embeddings failed)
            - embedding_available: False if the embedding model is unavailable
        """
        try:
            scores = self._compute_embedding_scores(user, candidates)
            return scores, True
        except Exception as e:
            logger.warning(
                f"Embedding scoring failed, falling back to LLM-only: {e}"
            )
            return [0.0] * len(candidates), False

    def _compute_embedding_scores(
        self, user: Persona, candidates: list[Persona]
    ) -> list[float]:
        """Compute embedding cosine similarity between user and all candidates."""
        # Get user embedding (cached)
        user_embedding = self._get_embedding(user)

        # Batch embed candidates
        texts = [c.to_embedding_text() for c in candidates]
        candidate_embeddings = self.client.embed(texts)

        scores = []
        for i, candidate in enumerate(candidates):
            score = self.client.cosine_similarity(user_embedding, candidate_embeddings[i])
            # Normalize to 0-1 range (cosine can be negative)
            normalized = (score + 1.0) / 2.0
            scores.append(normalized)
            # Cache
            self._embedding_cache[candidate.id] = candidate_embeddings[i]

        return scores

    def _get_embedding(self, persona: Persona) -> list[float]:
        """Get embedding for a persona, using cache if available."""
        if persona.id in self._embedding_cache:
            return self._embedding_cache[persona.id]

        result = self.client.embed([persona.to_embedding_text()])
        self._embedding_cache[persona.id] = result[0]
        return result[0]

    def _llm_compatibility_score(
        self,
        user: Persona,
        candidate: Persona,
        rejection_reasons: list[str],
    ) -> CompatibilityScore:
        """Use LLM chain-of-thought reasoning to assess compatibility."""

        rejection_context = ""
        if rejection_reasons:
            rejection_context = (
                "\nPREVIOUS REJECTION REASONS (avoid matching on these traits):\n"
                + "\n".join(f"- {r}" for r in rejection_reasons)
            )

        prompt = f"""Assess the compatibility between these two college students for dating.

STUDENT A (seeking a match):
{user.to_profile_summary()}
Looking for: {user.date_type.value}
Preferences: {json.dumps(user.dating_preferences.model_dump(), default=str)}

STUDENT B (potential match):
{candidate.to_profile_summary()}
Looking for: {candidate.date_type.value}
{rejection_context}

Think step by step:
1. Do their date types align? (life_partner + casual = bad fit)
2. Do they share meaningful interests beyond surface level?
3. Are their communication styles compatible?
4. Does Student B meet Student A's physical/demographic preferences?
5. Would they realistically enjoy spending time together?

Give a compatibility score from 0.0 (terrible match) to 1.0 (perfect match).
Be realistic — most matches should score 0.3-0.7. Reserve 0.8+ for genuinely excellent fits."""

        system_prompt = (
            "You are an expert matchmaking compatibility assessor. "
            "Evaluate dating compatibility with nuance and realism. "
            "Output strict JSON matching the schema."
        )

        try:
            return self.client.generate_structured(
                prompt=prompt,
                response_schema=CompatibilityScore,
                system_prompt=system_prompt,
                temperature=0.3,
            )
        except (ValueError, Exception) as e:
            logger.warning(
                "LLM compatibility scoring failed for %s vs %s: %s",
                user.name, candidate.name, e,
            )
            return CompatibilityScore(
                score=0.5,
                justification="LLM scoring unavailable — using neutral fallback score",
                shared_interests=[],
                potential_issues=["scoring_unavailable"],
            )
