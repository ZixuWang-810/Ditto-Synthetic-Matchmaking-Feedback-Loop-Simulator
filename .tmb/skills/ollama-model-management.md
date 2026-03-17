# Ollama Python SDK — Model Management

## Installation

```bash
uv add ollama
```

## Client Setup

```python
import ollama

# Default (localhost:11434)
client = ollama.Client()

# Custom host
client = ollama.Client(host="http://localhost:11434")
```

## Check If a Model Exists

```python
def model_exists(client: ollama.Client, model_name: str) -> bool:
    """Check if a model is already pulled locally."""
    try:
        models = client.list()
        # models is a dict with key "models", each entry has a "name" field
        # Model names may include tags like "nomic-embed-text:latest"
        return any(
            m.model.startswith(model_name)
            for m in models.models
        )
    except Exception:
        return False
```

## Pull a Model

```python
# Synchronous pull (blocks until complete — can take minutes for large models)
client.pull(model="nomic-embed-text")

# The pull method streams progress by default. In the Python SDK,
# it returns a generator of progress dicts when stream=True:
for progress in client.pull(model="nomic-embed-text", stream=True):
    print(progress.get("status"), progress.get("completed"), progress.get("total"))
```

**Key facts about `client.pull()`:**
- Blocks until the model is fully downloaded (synchronous by default)
- `nomic-embed-text` is ~274MB — takes 10-60 seconds depending on connection
- If the model is already pulled, it completes almost instantly (no re-download)
- Raises `ollama.ResponseError` if the model name is invalid or Ollama can't reach the registry

## Lazy Auto-Pull Pattern (Recommended for This Project)

The pattern: attempt the operation, catch the 404, pull the model, retry once.

```python
import logging
import ollama

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, embedding_model: str = "nomic-embed-text"):
        self.embedding_model = embedding_model
        self._client = None
        self._embedding_model_verified = False  # Only pull once per process

    def _get_client(self):
        if self._client is None:
            self._client = ollama.Client(host="http://localhost:11434")
        return self._client

    def get_embedding(self, text: str) -> list[float]:
        client = self._get_client()

        # Fast path: model already verified
        if self._embedding_model_verified:
            response = client.embed(model=self.embedding_model, input=text)
            return response["embeddings"][0]

        # First call: try, and auto-pull on 404
        try:
            response = client.embed(model=self.embedding_model, input=text)
            self._embedding_model_verified = True
            return response["embeddings"][0]
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "404" in error_str:
                logger.info(
                    f"Embedding model '{self.embedding_model}' not found locally. "
                    f"Pulling now (this may take a moment)..."
                )
                try:
                    client.pull(model=self.embedding_model)
                    logger.info(f"Successfully pulled '{self.embedding_model}'")
                    self._embedding_model_verified = True
                    # Retry the embedding call
                    response = client.embed(model=self.embedding_model, input=text)
                    return response["embeddings"][0]
                except Exception as pull_err:
                    logger.warning(
                        f"Failed to pull '{self.embedding_model}': {pull_err}. "
                        f"Embedding scoring will be unavailable."
                    )
                    raise  # Let caller handle the fallback
            else:
                raise  # Non-404 error — re-raise
```

## Error Types

```python
import ollama

try:
    client.embed(model="nonexistent-model", input="test")
except ollama.ResponseError as e:
    # e.status_code == 404 for model not found
    # e.error contains the message string
    print(e.status_code, e.error)
except ConnectionError:
    # Ollama server not running
    pass
```

**`ollama.ResponseError`** is the main error class. Key attributes:
- `status_code`: HTTP status (404 for model not found)
- `error`: Human-readable error message

## Gotchas

1. **Class-level flag**: Use `_embedding_model_verified` as an **instance** attribute, not class-level, if you create multiple `LLMClient` instances with different embedding models.

2. **Thread safety**: If multiple threads call `get_embedding()` simultaneously before the model is pulled, you might get multiple pull attempts. This is harmless (Ollama deduplicates) but noisy. Use a threading lock if needed.

3. **Model name variants**: Ollama model names can include tags (`nomic-embed-text:latest`). The `pull()` call works with or without the tag — it defaults to `:latest`.

4. **Disk space**: Pulling a model requires disk space. `nomic-embed-text` is ~274MB. If disk is full, the pull will fail with an OS error, not an `ollama.ResponseError`.

5. **Network required**: `client.pull()` requires internet access to download from the Ollama registry. In air-gapped environments, this will fail.

## Testing the Auto-Pull

```python
from unittest.mock import MagicMock, patch

def test_auto_pull_on_missing_model():
    """Verify that get_embedding auto-pulls when model is missing."""
    client = LLMClient(embedding_model="nomic-embed-text")
    mock_ollama = MagicMock()
    client._client = mock_ollama
    
    # First call raises 404, second call (after pull) succeeds
    mock_ollama.embed.side_effect = [
        Exception('model "nomic-embed-text" not found, try pulling it first (status code: 404)'),
        {"embeddings": [[0.1, 0.2, 0.3]]},
    ]
    mock_ollama.pull.return_value = None  # Pull succeeds
    
    result = client.get_embedding("test text")
    
    assert result == [0.1, 0.2, 0.3]
    mock_ollama.pull.assert_called_once_with(model="nomic-embed-text")
    assert client._embedding_model_verified is True
```
