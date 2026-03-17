# Matcher Fallback Pattern

## Context
`src/ditto_bot/matcher.py` contains `MatchScorer` which calls `LLMClient.generate_structured()` to get a `CompatibilityScore`. When the LLM returns malformed JSON, the call raises `ValueError` and crashes the entire simulation. The fix is to catch failures in the matcher and return a neutral fallback score.

## The CompatibilityScore Model
```python
class CompatibilityScore(BaseModel):
    """Structured LLM output for compatibility assessment."""
    score: float = Field(ge=0.0, le=1.0, description="Compatibility score 0-1")
    justification: str = Field(description="Why these two people are/aren't compatible")
    shared_interests: list[str] = Field(default_factory=list)
    potential_issues: list[str] = Field(default_factory=list)
```

## Neutral Fallback Instance
When LLM scoring fails completely (after repair + retry), return this instead of crashing:
```python
NEUTRAL_FALLBACK = CompatibilityScore(
    score=0.5,
    justification="LLM scoring unavailable — using neutral fallback score",
    shared_interests=[],
    potential_issues=["scoring_unavailable"],
)
```

**Why 0.5?** It's the midpoint — won't surface the candidate as a top match (those score 0.7+), but won't unfairly exclude them either. The simulation continues.

## Where to Apply — `_llm_compatibility_score()`
The method at ~line 255 in `matcher.py` calls `self.client.generate_structured()`. Wrap it:

```python
def _llm_compatibility_score(
    self, user: Persona, candidate: Persona, rejection_reasons: list[str]
) -> CompatibilityScore:
    prompt = ...  # existing prompt construction
    try:
        return self.client.generate_structured(
            prompt=prompt,
            response_model=CompatibilityScore,
            temperature=0.3,
        )
    except (ValueError, Exception) as e:
        logger.warning(
            f"LLM compatibility scoring failed for {user.name} vs {candidate.name}: {e}"
        )
        return CompatibilityScore(
            score=0.5,
            justification="LLM scoring unavailable — using neutral fallback score",
            shared_interests=[],
            potential_issues=["scoring_unavailable"],
        )
```

## Key Design Decisions
1. **Catch at `_llm_compatibility_score` level** — not higher. This way each candidate is scored independently; one failure doesn't block others.
2. **Log a warning** — operators can see which pairs failed and investigate.
3. **Include `"scoring_unavailable"` in potential_issues** — downstream code can detect fallback scores if needed.
4. **Don't catch at `score_candidates` level** — that would skip ALL remaining candidates on first failure.

## Interaction with Retry in client.py
The 3-layer defense works like this:
1. `generate_structured()` tries to parse → fails
2. `generate_structured()` runs `repair_json()` → may succeed (most cases)
3. `generate_structured()` retries with nudge prompt → may succeed
4. If all fail, `generate_structured()` raises `ValueError`
5. `_llm_compatibility_score()` catches `ValueError` → returns neutral fallback
6. Simulation continues with 0.5 score for that pair
