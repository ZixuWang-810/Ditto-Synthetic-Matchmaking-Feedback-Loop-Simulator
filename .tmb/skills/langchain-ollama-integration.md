# LangChain-Ollama Integration

## Installation

```bash
uv add langchain-ollama langchain-core
```

## ChatOllama — Chat Completions

```python
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

llm = ChatOllama(
    model="llama3.2",
    base_url="http://localhost:11434",
    temperature=0.8,
)

# Basic invocation
response = llm.invoke([
    SystemMessage(content="You are a helpful assistant."),
    HumanMessage(content="Hello!"),
])
print(response.content)  # str
print(type(response))    # AIMessage
```

## Structured Output with Pydantic

```python
from pydantic import BaseModel, Field

class MatchEvaluation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    justification: str
    shared_interests: list[str] = Field(default_factory=list)

# Method 1: with_structured_output (preferred for LangGraph)
structured_llm = llm.with_structured_output(MatchEvaluation)
result = structured_llm.invoke([
    SystemMessage(content="Evaluate compatibility..."),
    HumanMessage(content="Profile A vs Profile B..."),
])
# result is a MatchEvaluation instance (not an AIMessage!)
print(result.score, result.justification)
```

**Gotcha**: `with_structured_output()` returns the Pydantic model directly, NOT an AIMessage. Plan your node return values accordingly.

**Gotcha**: Not all Ollama models support structured output well. `llama3.2` works. Smaller models may produce malformed JSON. Always wrap in try/except.

## OllamaEmbeddings

```python
from langchain_ollama import OllamaEmbeddings

embeddings = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url="http://localhost:11434",
)

# Single text
vector = embeddings.embed_query("I love hiking and outdoor activities")
# Returns list[float]

# Batch
vectors = embeddings.embed_documents(["text1", "text2", "text3"])
# Returns list[list[float]]
```

## Using with LangGraph Nodes

```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

def my_node(state: dict) -> dict:
    """LangGraph node using ChatOllama."""
    llm = ChatOllama(model="llama3.2", base_url="http://localhost:11434")
    
    # Build messages from state
    messages = [SystemMessage(content="You are Ditto...")] + state["messages"]
    
    # Invoke
    response = llm.invoke(messages)
    
    # Return update — response is an AIMessage, compatible with add_messages
    return {"messages": [response]}
```

## Mixing with Existing Ollama Client

If you have an existing raw `ollama.Client` (like `src/llm/client.py`), you can use BOTH:
- **ChatOllama** for LangGraph nodes that need LangChain message types
- **Raw ollama client** for existing code (MatchScorer, embeddings) that works fine as-is

```python
# In your graph module — use ChatOllama
from langchain_ollama import ChatOllama
graph_llm = ChatOllama(model="llama3.2", base_url="http://localhost:11434")

# In your existing matcher — keep using raw ollama
from src.llm.client import get_llm_client
raw_client = get_llm_client()  # Your existing LLMClient wrapper
```

No need to migrate everything at once. The two can coexist.

## Message Type Conversion

If you need to convert between LangChain messages and plain dicts:

```python
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Dict → LangChain message
def dict_to_message(d: dict) -> BaseMessage:
    role = d["role"]
    content = d["content"]
    if role == "user":
        return HumanMessage(content=content)
    elif role == "assistant":
        return AIMessage(content=content)
    elif role == "system":
        return SystemMessage(content=content)

# LangChain message → dict
def message_to_dict(m: BaseMessage) -> dict:
    if isinstance(m, HumanMessage):
        return {"role": "user", "content": m.content}
    elif isinstance(m, AIMessage):
        return {"role": "assistant", "content": m.content}
    elif isinstance(m, SystemMessage):
        return {"role": "system", "content": m.content}
```

This is useful when interfacing LangGraph state (LangChain messages) with existing code that expects plain dicts.

## Error Handling

```python
from langchain_core.exceptions import OutputParserException

try:
    result = structured_llm.invoke(messages)
except OutputParserException as e:
    # LLM returned malformed JSON
    logger.warning(f"Structured output failed: {e}")
    # Retry or fallback
except Exception as e:
    # Ollama not running, model not pulled, etc.
    logger.error(f"LLM call failed: {e}")
    raise
```

## Performance Tips

- **Reuse the ChatOllama instance** — don't create a new one per node invocation. Initialize once and pass via closure or module-level variable.
- **Temperature 0.0** for structured output / scoring tasks, **0.7-0.8** for creative conversation.
- Ollama keeps models loaded in memory after first call. First invocation is slow (model loading), subsequent calls are fast.
