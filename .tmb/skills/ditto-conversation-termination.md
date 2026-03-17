# Ditto Conversation Termination Patterns

## Problem

The Ditto matchmaking graph can enter an infinite loop when:
1. All candidates have been shown (pool exhausted)
2. All candidates are filtered out by hard preference filters
3. `score_candidates()` returns an empty list

The loop path is: `handle_rejection → score_matches → route_after_scoring → present_match → ...` but when there are no candidates, `score_matches_node` sets `current_match = None`, and if `route_after_scoring` doesn't handle this, the graph has no valid exit.

## Architecture Context

### The Graph Flow (from `src/ditto_bot/graph.py`)

```
handle_rejection → score_matches → route_after_scoring → {present_match | completed(END)}
```

The `route_after_scoring` function is the **critical decision point**. It must handle:
- ✅ Normal case: `current_match` is set → route to `present_match`
- ✅ Max rounds exceeded: `current_round >= max_rounds` → route to `completed` (END)
- ❌ **Missing case**: No eligible candidates → should route to `completed` (END)

### Key State Fields

```python
class DittoState(TypedDict):
    current_match: dict | None    # None when no candidates available
    current_round: int            # Incremented each scoring round
    max_rounds: int               # Hard limit (default 6 from config.MAX_MATCH_ROUNDS)
    shown_match_ids: list[str]    # Already-shown match IDs
    phase: str                    # Current conversation phase
```

## Fix: Two-Layer Defense

### Layer 1: `score_matches_node` (in `src/ditto_bot/nodes.py`)

When `MatchScorer.score_candidates()` returns an empty list, the node should:
1. Set `current_match = None` explicitly
2. Set `phase = "completed"` 
3. Append an `AIMessage` with a graceful exit message
4. Log the exhaustion event

```python
def score_matches_node(state: DittoState) -> dict[str, Any]:
    # ... existing scoring logic ...
    
    results = scorer.score_candidates(
        user=user_persona,
        candidates=candidates,
        rejection_reasons=state.get("rejection_reasons", []),
        shown_ids=set(state.get("shown_match_ids", [])),
    )
    
    if not results:
        # No eligible candidates remaining
        logger.info("No eligible candidates remaining — ending conversation")
        return {
            "messages": [AIMessage(content=(
                "I've gone through all my available matches for you. "
                "Let's wrap up for now — check back soon for new people!"
            ))],
            "current_match": None,
            "phase": "completed",
        }
    
    # Normal path: set best match
    best = results[0]
    return {
        "current_match": best.candidate.model_dump(),
        "current_round": state["current_round"] + 1,
        "shown_match_ids": state["shown_match_ids"] + [best.candidate.id],
    }
```

### Layer 2: `route_after_scoring` (in `src/ditto_bot/graph.py`)

Belt-and-suspenders guard — even if the node doesn't set phase correctly:

```python
def route_after_scoring(state: DittoState) -> str:
    """Route after score_matches: present match or end conversation."""
    # Guard 1: No match found (pool exhausted)
    if state.get("current_match") is None:
        return "completed"
    
    # Guard 2: Max rounds exceeded
    if state["current_round"] >= state["max_rounds"]:
        return "completed"
    
    # Normal: present the match
    return "present_match"
```

**Critical**: The `current_match is None` check MUST come BEFORE the max_rounds check. If the pool is exhausted at round 2 of 6, we still need to exit.

## Termination Conditions Summary

| Condition | Where Detected | Action |
|-----------|---------------|--------|
| `current_round >= max_rounds` | `route_after_scoring` | Route to `completed` → END |
| `score_candidates()` returns `[]` | `score_matches_node` | Set `current_match = None`, phase = `completed`, add exit message |
| `current_match is None` | `route_after_scoring` | Route to `completed` → END (belt-and-suspenders) |

## Testing

```python
def test_route_after_scoring_no_candidates():
    """When current_match is None, route to completed."""
    from src.ditto_bot.graph import route_after_scoring
    
    state = {
        "current_match": None,
        "current_round": 2,
        "max_rounds": 6,
        "phase": "completed",
    }
    assert route_after_scoring(state) == "completed"


def test_route_after_scoring_max_rounds():
    """When max rounds exceeded, route to completed."""
    from src.ditto_bot.graph import route_after_scoring
    
    state = {
        "current_match": {"id": "some-id", "name": "Test"},
        "current_round": 6,
        "max_rounds": 6,
        "phase": "presenting_match",
    }
    assert route_after_scoring(state) == "completed"


def test_route_after_scoring_normal():
    """When match exists and rounds remaining, route to present_match."""
    from src.ditto_bot.graph import route_after_scoring
    
    state = {
        "current_match": {"id": "some-id", "name": "Test"},
        "current_round": 2,
        "max_rounds": 6,
        "phase": "presenting_match",
    }
    assert route_after_scoring(state) == "present_match"
```

## Gotchas

1. **`current_match` vs `None`**: In `DittoState`, `current_match` is typed as `dict | None`. After a successful scoring round, it's a dict. After exhaustion, it must be explicitly set to `None`. Don't rely on it being absent from the state — LangGraph state fields persist across invocations.

2. **`shown_match_ids` accumulation**: The `shown_match_ids` list grows across rounds. Make sure the node appends to the existing list (not replaces it). The state reducer for this field is replacement, so you must include all previous IDs plus the new one.

3. **AIMessage for graceful exit**: The exit message should be added in `score_matches_node`, NOT in a separate node. This ensures the user sees a message before the graph terminates. Without it, the conversation ends silently.

4. **Phase consistency**: Setting `phase = "completed"` in the node is good practice for logging/analytics, but the actual termination is controlled by `route_after_scoring` returning `"completed"` which maps to `END` in the graph edges.
