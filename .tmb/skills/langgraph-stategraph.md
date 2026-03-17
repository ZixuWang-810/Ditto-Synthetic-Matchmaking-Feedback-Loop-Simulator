# LangGraph StateGraph Patterns

## Installation

```bash
uv add langgraph langchain-core langchain-ollama
```

## Core Concept

LangGraph models agent logic as a **directed graph** where:
- **Nodes** are Python functions that read/write a shared **state** (TypedDict)
- **Edges** define transitions (unconditional or conditional)
- **State** is a TypedDict that flows through the graph, updated by each node via dict returns

## 1. Define State

```python
from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class ConversationState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # Auto-appends
    phase: str
    current_round: int
    max_rounds: int
    user_preferences: list[str]
    rejection_reasons: list[str]
    # Add any fields your graph needs
```

**Key pattern**: Use `Annotated[list[BaseMessage], add_messages]` for the messages field. The `add_messages` reducer **appends** new messages instead of replacing the list. For all other fields, returning a key in the node's dict **replaces** the value.

## 2. Define Nodes

Each node is a function that takes state and returns a **partial dict** of updates:

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

def greeting_node(state: ConversationState) -> dict:
    """Generate the greeting message."""
    # Access state
    phase = state["phase"]
    
    # Do work (call LLM, compute scores, etc.)
    response = llm.invoke([SystemMessage(content="You are Ditto..."), 
                           HumanMessage(content="Start the conversation")])
    
    # Return ONLY the fields you want to update
    return {
        "messages": [response],  # add_messages will append this
        "phase": "collecting_preferences",
    }
```

**Gotcha**: Nodes must return a dict, not the full state. Only include keys you want to update. Missing keys are left unchanged.

## 3. Build the Graph

```python
from langgraph.graph import StateGraph, START, END

# Create graph builder with state schema
builder = StateGraph(ConversationState)

# Add nodes
builder.add_node("greeting", greeting_node)
builder.add_node("collect_preferences", collect_preferences_node)
builder.add_node("score_matches", score_matches_node)
builder.add_node("present_match", present_match_node)
builder.add_node("handle_rejection", handle_rejection_node)
builder.add_node("date_proposal", date_proposal_node)
builder.add_node("collect_feedback", collect_feedback_node)

# Add edges
builder.add_edge(START, "greeting")
builder.add_edge("greeting", "collect_preferences")
builder.add_edge("collect_preferences", "score_matches")
builder.add_edge("score_matches", "present_match")

# Conditional edge based on state
def route_after_match(state: ConversationState) -> str:
    """Decide next node after presenting a match."""
    if state.get("match_accepted"):
        return "date_proposal"
    if state["current_round"] >= state["max_rounds"]:
        return END
    return "handle_rejection"

builder.add_conditional_edges(
    "present_match",
    route_after_match,
    # Optional: explicit mapping for clarity
    {
        "date_proposal": "date_proposal",
        "handle_rejection": "handle_rejection",
        END: END,
    }
)

builder.add_edge("handle_rejection", "score_matches")  # Loop back
builder.add_edge("date_proposal", "collect_feedback")
builder.add_edge("collect_feedback", END)

# Compile
graph = builder.compile()
```

## 4. Run the Graph

```python
# Initial state
initial_state = {
    "messages": [],
    "phase": "greeting",
    "current_round": 0,
    "max_rounds": 6,
    "user_preferences": [],
    "rejection_reasons": [],
}

# Run to completion
final_state = graph.invoke(initial_state)

# Or stream node-by-node (great for Streamlit)
for event in graph.stream(initial_state):
    # event is {node_name: state_update}
    for node_name, update in event.items():
        print(f"Node '{node_name}' executed")
```

## 5. Conditional Edges — The Router Pattern

```python
def should_continue(state: ConversationState) -> str:
    """Router function — returns the NAME of the next node (or END)."""
    if state.get("dropped_off"):
        return END
    if state.get("match_accepted"):
        return "date_proposal"
    if state["current_round"] >= state["max_rounds"]:
        return END
    return "handle_rejection"

# The third argument maps return values to node names
builder.add_conditional_edges(
    "present_match",
    should_continue,
    {"date_proposal": "date_proposal", "handle_rejection": "handle_rejection", END: END}
)
```

## 6. Using LangChain Chat Models with Ollama

```python
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="llama3.2",
    base_url="http://localhost:11434",
    temperature=0.8,
)

# Use in a node
def my_node(state: ConversationState) -> dict:
    response = llm.invoke(state["messages"])
    return {"messages": [response]}
```

## Gotchas

1. **`add_messages` reducer**: Only use on the `messages` field. Other list fields (like `rejection_reasons`) will be **replaced**, not appended. To append, do it explicitly in the node: `return {"rejection_reasons": state["rejection_reasons"] + [new_reason]}`.

2. **Node return type**: Always return a `dict`. Returning `None` or the full state object will cause errors.

3. **Conditional edge return values**: Must return a string that matches a node name or `END`. If using the explicit mapping dict, every possible return value must be in the mapping.

4. **Graph is immutable after compile**: Call `builder.compile()` once. To modify, create a new builder.

5. **State is passed by value between nodes**: Each node gets a copy. Mutations to the state dict inside a node don't propagate — only the returned dict matters.

6. **Streaming**: `graph.stream()` yields one dict per node execution: `{node_name: state_update_from_that_node}`. Use `graph.stream(state, stream_mode="values")` to get the full accumulated state after each node instead.

7. **END constant**: Import from `langgraph.graph`: `from langgraph.graph import END`. Don't use the string `"__end__"` directly.

## Integration with Existing Code

When wrapping existing logic (like a MatchScorer class) into a LangGraph node:

```python
# Keep your existing class
scorer = MatchScorer(llm_client=existing_client)

# Wrap it in a node function
def score_matches_node(state: ConversationState) -> dict:
    results = scorer.score_candidates(
        user=state["user_persona"],
        candidates=state["persona_pool"],
        rejection_reasons=state["rejection_reasons"],
        shown_ids=state["shown_match_ids"],
    )
    best = results[0] if results else None
    return {
        "current_match": best,
        "current_round": state["current_round"] + 1,
    }
```

This lets you adopt LangGraph incrementally without rewriting business logic.
