# Ditto Bot LangGraph Routing Architecture

## Overview

The Ditto matchmaking conversation is implemented as a LangGraph `StateGraph` in `src/ditto_bot/graph.py`. The graph manages a multi-phase conversation between the Ditto Bot (AI matchmaker) and a Customer Bot (simulated user).

## State Schema — `DittoState`

```python
class DittoState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # append-only via reducer
    phase: str                    # Current ConversationPhase value
    user_persona: dict            # User's persona as plain dict
    persona_pool: list[dict]      # All candidate personas as dicts
    user_preferences: list[str]   # Extracted preference statements
    rejection_reasons: list[str]  # Why user rejected previous matches
    shown_match_ids: list[str]    # IDs of already-presented matches
    current_match: dict | None    # Currently presented match (None until score_matches runs)
    accepted_match: dict | None   # Accepted match (None until user accepts)
    current_round: int            # Current match round number
    max_rounds: int               # Max allowed rounds
    llm_model: str                # Ollama model name for chat
    embedding_model: str          # Ollama model name for embeddings
```

**Critical**: `current_match` starts as `None` and is only populated by `score_matches_node`. Any node that reads `current_match` MUST verify it's not `None`.

## Node Functions (in `src/ditto_bot/nodes.py`)

| Node | Purpose | Sets Phase To |
|------|---------|---------------|
| `greeting_node` | Opening message, asks what user is looking for | `collecting_preferences` |
| `collect_preferences_node` | Extracts preferences from conversation | `presenting_match` (when done) |
| `score_matches_node` | Runs `MatchScorer.score_candidates()`, sets `current_match` | (no phase change) |
| `present_match_node` | Presents the top match to user | `presenting_match` |
| `date_proposal_node` | Proposes a date after acceptance | `date_proposal` |
| `rejection_handling_node` | Handles rejection, extracts reason | `handling_rejection` |
| `post_date_feedback_node` | Collects post-date feedback | `completed` |

## Graph Construction — `build_ditto_graph()`

```python
def build_ditto_graph() -> CompiledStateGraph:
    g = StateGraph(DittoState)

    # Add all nodes
    g.add_node("greeting", greeting_node)
    g.add_node("collect_preferences", collect_preferences_node)
    g.add_node("score_matches", score_matches_node)
    g.add_node("present_match", present_match_node)
    g.add_node("date_proposal", date_proposal_node)
    g.add_node("handle_rejection", handle_rejection_node)
    g.add_node("collect_feedback", collect_feedback_node)

    # Entry: conditional dispatch from START
    g.add_conditional_edges(START, route_after_user_response, {
        "greeting": "greeting",
        "collect_preferences": "collect_preferences",
        "score_matches": "score_matches",   # belt-and-suspenders fallback
        "handle_rejection": "handle_rejection",
        "date_proposal": "date_proposal",
        "collect_feedback": "collect_feedback",
        "completed": END,
    })

    # collect_preferences: conditional edge — chains to score_matches when
    # preferences are complete (phase == 'presenting_match'), otherwise END.
    # This ensures score_matches → present_match runs in the same invocation
    # so current_match is never None when the user next responds.
    g.add_conditional_edges(
        "collect_preferences",
        route_after_collect_preferences,
        {"score_matches": "score_matches", END: END},
    )

    # Internal chain: rejection → re-score → present
    g.add_edge("handle_rejection", "score_matches")
    g.add_conditional_edges("score_matches", route_after_scoring, {
        "present_match": "present_match",
        "completed": END,
    })

    # Terminal nodes → END
    g.add_edge("greeting", END)
    g.add_edge("present_match", END)   # Returns match presentation, waits for user
    g.add_edge("date_proposal", END)
    g.add_edge("collect_feedback", END)

    return g.compile()
```

### `route_after_collect_preferences` (new in branch 10)

```python
def route_after_collect_preferences(state: DittoState) -> str:
    """Conditional edge after collect_preferences_node.

    When the node sets phase='presenting_match', chain directly into
    score_matches (→ present_match → END) within the same invocation.
    Otherwise return END and wait for the next user message.
    """
    if state.get("phase") == "presenting_match":
        return "score_matches"
    return END
```

## Routing Function — `route_after_user_response`

This is the main router called after each Customer Bot message is injected as a `HumanMessage`:

```python
def route_after_user_response(state: DittoState) -> str:
    phase = state.get("phase", "")

    if phase == "greeting":
        return "greeting"

    if phase == "collecting_preferences":
        return "collect_preferences"

    if phase == "presenting_match":
        # Belt-and-suspenders: if score_matches hasn't run yet, route there now.
        if state.get("current_match") is None:
            return "score_matches"
        user_text = _last_user_content(state)
        if _is_acceptance(user_text):
            return "date_proposal"
        if state["current_round"] < state["max_rounds"]:
            return "handle_rejection"
        return "completed"

    if phase == "post_date_feedback":
        return "collect_feedback"

    return "completed"
```

## Acceptance Signal Detection

```python
_ACCEPTANCE_SIGNALS = (
    "yes", "sounds great", "let's do it", "lets do it", "i accept",
    "sure", "love it", "absolutely", "why not", "i'd love", "id love",
    "down", "count me in", "let's go", "i'm in",
)

def _is_acceptance(text: str) -> bool:
    return any(signal in text for signal in _ACCEPTANCE_SIGNALS)
```

**Note**: Common casual words (`"great"`, `"perfect"`, `"awesome"`, `"ok"`, `"okay"`) were removed to prevent false positives via substring matching. Only intentional acceptance phrases are kept. The `current_match is not None` guard in `route_after_user_response` provides an additional safety layer.

## How the Engine Invokes the Graph

In `src/orchestrator/engine.py`, the `_run_conversation` method:
1. Calls `graph.invoke(initial_state)` for the greeting
2. Loops: sends Ditto's response to CustomerBot, gets reply, injects as HumanMessage, calls `graph.invoke(updated_state)`
3. The graph runs one "turn" per invocation — from user response through routing to the next Ditto response

The engine does NOT manage phases — the graph's conditional edges handle all routing internally.

## Routing Gap Fix (branch 10)

**Problem**: When `collect_preferences_node` sets `phase = "presenting_match"` and returns to `END`, the next user response enters `route_after_user_response` with `phase == "presenting_match"` but `current_match is None` (because `score_matches` never ran). This caused misrouting to `date_proposal` or `rejection_handling` with no match data.

**Fix**: Two-layer defence:
1. **Conditional edge** from `collect_preferences` via `route_after_collect_preferences` chains directly to `score_matches` → `present_match` within the same invocation when preferences are complete.
2. **Guard in `route_after_user_response`**: if `current_match is None` and phase is `presenting_match`, route to `score_matches` instead of checking acceptance signals.
