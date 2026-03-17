# Ollama Raw Python Client — Structured Output

## Context
The project's `src/llm/client.py` uses the raw `ollama` Python package (NOT `langchain-ollama`) for LLM calls. The `LLMClient.generate_structured()` method uses `ollama.Client.chat()` with `format="json"` to get structured output.

## Installation
```bash
uv add ollama
```

## Basic Chat Call
```python
import ollama

client = ollama.Client(host="http://localhost:11434")

response = client.chat(
    model="llama3.2",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ],
    options={"temperature": 0.8},
)

text = response["message"]["content"]  # str
```

## Structured JSON Output
```python
response = client.chat(
    model="llama3.2",
    messages=[
        {"role": "system", "content": "Return valid JSON matching this schema..."},
        {"role": "user", "content": "Evaluate compatibility..."},
    ],
    format="json",  # Forces JSON mode — model MUST return JSON
    options={"temperature": 0.3},
)

raw_text = response["message"]["content"]  # str — should be JSON
parsed = json.loads(raw_text)  # May fail if LLM produces malformed JSON
```

## Key Gotchas

1. **`format="json"` is not foolproof**: Even with JSON mode, small models like `llama3.2` can produce:
   - Unescaped double quotes inside strings: `"height (5'5"` 
   - Truncated output (unclosed brackets/braces) from token limits
   - Trailing commas: `["a", "b",]`

2. **Response structure**: `response["message"]["content"]` is always a string. You must `json.loads()` it yourself.

3. **Error types**: 
   - `ollama.ResponseError` — model not found, server error
   - `ConnectionError` — Ollama not running
   - `json.JSONDecodeError` — malformed JSON from model
   - `pydantic.ValidationError` — JSON is valid but doesn't match schema

4. **Retry pattern for structured output**:
```python
def generate_structured_with_retry(
    client, model, messages, response_model, max_attempts=2, temperature=0.3
):
    """Generate structured output with repair and retry."""
    for attempt in range(max_attempts):
        response = client.chat(
            model=model,
            messages=messages,
            format="json",
            options={"temperature": temperature},
        )
        raw_text = response["message"]["content"]
        
        # Try direct parse first
        try:
            return response_model.model_validate_json(raw_text)
        except Exception:
            pass
        
        # Try repair
        repaired = repair_json(raw_text)
        if repaired is not None:
            try:
                return response_model.model_validate(repaired)
            except Exception:
                pass
        
        # On retry, add a nudge message
        if attempt < max_attempts - 1:
            messages = messages + [
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": "Your response was not valid JSON. Please return ONLY a valid JSON object."},
            ]
    
    raise ValueError(f"Failed after {max_attempts} attempts. Last raw: {raw_text[:500]}")
```

5. **The `options` parameter** accepts Ollama model options:
   - `temperature`: 0.0-2.0 (lower = more deterministic)
   - `num_predict`: max tokens to generate (-1 for unlimited)
   - `top_p`, `top_k`: sampling parameters

## Embedding Calls (for reference)
```python
response = client.embed(model="nomic-embed-text", input="some text")
vector = response["embeddings"][0]  # list[float]
```
