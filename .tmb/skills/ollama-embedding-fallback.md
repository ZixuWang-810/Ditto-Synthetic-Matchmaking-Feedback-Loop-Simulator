# Ollama Embedding Fallback Pattern

## Problem

The `MatchScorer` in `src/ditto_bot/matcher.py` calls Ollama's embedding endpoint with `nomic-embed-text`. If the model isn't pulled locally, Ollama returns a 404 error that crashes the entire conversation.

## Architecture Context

The scoring pipeline in `matcher.py` uses a **hybrid approach**:
- **Embedding cosine similarity** (40% weight via `config.EMBEDDING_SCORE_WEIGHT`)
- **LLM compatibility reasoning** (60% weight via `config.LLM_SCORE_WEIGHT`)

The embedding call happens in `MatchScorer._get_embedding()` which calls `self.client.get_embedding(text)`.

## The LLMClient Embedding Method

In `src/llm/client.py`:
```python
def get_embedding(self, text: str) -> list[float]:
    client = self._get_client()
    response = client.embed(model=self.embedding_model, input=text)
    return response["embeddings"][0]
```

This uses the `ollama` Python package directly (not langchain). The error surfaces as:
```
model "nomic-embed-text" not found, try pulling it first (status code: 404)
```

## Fix Pattern: Try/Except with LLM-Only Fallback

Wrap the embedding scoring in `MatchScorer.score_candidates()` or `_compute_embedding_score()` with a try/except:

```python
def _compute_embedding_score(self, user: Persona, candidate: Persona) -> float:
    """Compute embedding cosine similarity. Returns 0.0 on failure."""
    try:
        user_text = user.to_profile_summary()
        candidate_text = candidate.to_profile_summary()
        user_emb = self._get_embedding(user_text)
        candidate_emb = self._get_embedding(candidate_text)
        return self._cosine_similarity(user_emb, candidate_emb)
    except Exception as e:
        logger.warning(
            f"Embedding scoring failed (falling back to LLM-only): {e}"
        )
        return 0.0
```

Then in the combined score calculation, when embedding fails, use **100% LLM weight**:

```python
if embedding_score == 0.0 and embedding_failed:
    # Full weight on LLM score when embeddings unavailable
    combined = llm_score
else:
    combined = (
        config.EMBEDDING_SCORE_WEIGHT * embedding_score
        + config.LLM_SCORE_WEIGHT * llm_score
    )
```

## Key Implementation Details

1. **Where to catch**: Catch at the `_compute_embedding_score` level (or equivalent), NOT at the top-level `score_candidates`. This way LLM scoring still runs.

2. **What to catch**: Catch broad `Exception` — Ollama can raise `ResponseError`, `ConnectionError`, or other types depending on the failure mode.

3. **Logging**: Use `logger.warning()` so the user sees the degradation but the conversation continues.

4. **MatchResult transparency**: Set `embedding_score=0.0` in the `MatchResult` so downstream consumers know embeddings weren't used.

5. **Flag for weight adjustment**: Track whether embedding failed so you can give LLM score 100% weight instead of the normal 60%. Without this, the combined score would be artificially low (0.4 * 0 + 0.6 * llm_score = only 60% of actual quality).

## Testing

To test without pulling the model:
```python
# Verify fallback works by temporarily setting an invalid embedding model
scorer = MatchScorer()
scorer.client.embedding_model = "nonexistent-model"
results = scorer.score_candidates(user, candidates)
assert len(results) > 0  # Should not crash
assert all(r.embedding_score == 0.0 for r in results)
```

## Config Reference

From `src/config.py`:
```python
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_SCORE_WEIGHT: float = 0.4
LLM_SCORE_WEIGHT: float = 0.6
```
