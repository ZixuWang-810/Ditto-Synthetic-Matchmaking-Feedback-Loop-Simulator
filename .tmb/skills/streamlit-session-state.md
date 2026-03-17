# Streamlit Session State & Real-Time UI Patterns

## Installation

```bash
uv add streamlit
```

## Session State Basics

Streamlit reruns the entire script on every interaction. Use `st.session_state` to persist data across reruns.

```python
import streamlit as st

# Initialize once
if "conversation_log" not in st.session_state:
    st.session_state.conversation_log = []

# Read/write
st.session_state.conversation_log.append({"role": "ditto", "content": "Hello!"})
```

## Real-Time Conversation Display

For streaming agent conversations to the UI:

```python
# Create a container for the chat
chat_container = st.container(height=500)

# Stream messages as they arrive
for event in graph.stream(initial_state):
    for node_name, update in event.items():
        if "messages" in update:
            for msg in update["messages"]:
                with chat_container:
                    role = "assistant" if isinstance(msg, AIMessage) else "user"
                    with st.chat_message(role):
                        st.write(msg.content)
```

## Expanders for Debug Info

```python
with st.expander("🧠 Agent Thought Process", expanded=False):
    st.json(state_update)  # Show raw state
    st.write(f"Phase: {state['phase']}")
    st.write(f"Round: {state['current_round']}")
```

## Button + State Pattern

```python
if st.button("Start Simulation ▶️", type="primary"):
    st.session_state.running = True
    # Run your logic here — it executes in this rerun
    
    # Display results
    for turn in results:
        st.write(turn)
    
    st.session_state.running = False
```

## Multi-Page App Structure

```
app.py              # Main page
pages/
  1_👤_Persona_Studio.py
  2_💬_Simulation_Arena.py
  3_📊_Analytics.py
```

Each page file is a standalone Streamlit script. Shared state lives in `st.session_state`.

## Gotchas

1. **Script reruns**: Every widget interaction reruns the ENTIRE page script. Long-running operations (like LLM calls) should be inside `if button_clicked:` blocks.
2. **Container ordering**: `st.container()` reserves space. Content added later appears in order within the container.
3. **`st.rerun()`**: Forces a rerun. Use sparingly — can cause infinite loops.
4. **Widget keys**: If you create widgets in a loop, each needs a unique `key` parameter.
5. **`st.stop()`**: Halts script execution. Useful for early exits (e.g., no data loaded).
