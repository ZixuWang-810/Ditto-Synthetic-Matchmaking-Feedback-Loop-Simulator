# Pytest Unit Testing Patterns

## Setup
```bash
# Already in dev dependencies — install with:
uv sync --group dev

# Run tests:
uv run pytest tests/ -v
uv run pytest tests/test_specific.py -v
uv run pytest tests/test_specific.py::test_function_name -v
```

## Pattern 1: Basic Test Structure with Fixtures

```python
# tests/test_example.py
import pytest
from unittest.mock import MagicMock, patch

# Fixtures for reusable test setup
@pytest.fixture
def mock_client():
    """Create a mock LLM client that doesn't hit real APIs."""
    client = MagicMock()
    client.chat.return_value = "mock response"
    return client

@pytest.fixture
def sample_data():
    """Provide sample test data."""
    return {"score": 0.7, "justification": "Good match"}

def test_basic_functionality(sample_data):
    assert sample_data["score"] == 0.7

def test_with_mock(mock_client):
    result = mock_client.chat()
    assert result == "mock response"
    mock_client.chat.assert_called_once()
```

## Pattern 2: Parametrized Tests (Multiple Inputs, One Test)

```python
import pytest

@pytest.mark.parametrize("input_json,expected_valid", [
    ('{"score": 0.5}', True),
    ('{"score": 0.5,}', True),       # trailing comma — should be repaired
    ('{"broken": "5\'5""}', True),    # unescaped quote — should be repaired
    ('not json at all', False),        # unrepairable
    ('{"unclosed": [1, 2', True),     # unclosed bracket — should be repaired
])
def test_json_repair(input_json, expected_valid):
    result = repair_json(input_json)
    if expected_valid:
        assert result is not None
    else:
        assert result is None
```

## Pattern 3: Mocking External Services (Ollama, MongoDB)

```python
from unittest.mock import patch, MagicMock

def test_generate_structured_with_mock():
    """Test structured output without hitting Ollama."""
    from src.llm.client import LLMClient
    
    client = LLMClient()
    
    # Mock the internal Ollama client
    mock_ollama = MagicMock()
    mock_ollama.chat.return_value = {
        "message": {"content": '{"score": 0.8, "justification": "Great match"}'}
    }
    client._client = mock_ollama
    
    # Now calls to client won't hit real Ollama
    result = client.chat([{"role": "user", "content": "test"}])
    assert "score" in result or isinstance(result, str)

# Using patch decorator
@patch('src.llm.client.ollama')
def test_with_patch(mock_ollama_module):
    mock_client_instance = MagicMock()
    mock_ollama_module.Client.return_value = mock_client_instance
    mock_client_instance.chat.return_value = {
        "message": {"content": '{"score": 0.5}'}
    }
    
    client = LLMClient()
    # client._get_client() will now return the mock
```

## Pattern 4: Testing Exception Handling

```python
import pytest

def test_raises_on_invalid_input():
    with pytest.raises(ValueError, match="Failed to parse"):
        some_function(bad_input)

def test_no_exception_on_fallback():
    """Ensure fallback returns valid result instead of raising."""
    result = function_with_fallback(broken_input)
    assert result is not None
    assert isinstance(result, ExpectedModel)
```

## Pattern 5: conftest.py for Shared Fixtures

```python
# tests/conftest.py
import pytest
import sys
from pathlib import Path

# Ensure project root is on path (usually not needed with uv, but safe)
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

@pytest.fixture
def sample_persona_dict():
    """Minimal persona dict for testing."""
    return {
        "id": "test-001",
        "name": "Test User",
        "age": 25,
        "gender": "female",
        # ... minimal required fields
    }
```

## Gotchas

1. **Import paths**: This project uses `from src.xxx import yyy` style imports. Tests must be run from the project root (`uv run pytest`) so `src` is importable.

2. **No real LLM calls in tests**: Always mock the Ollama client. Tests must be fast and not depend on external services.

3. **Pydantic model validation in tests**: Use `model_validate()` for dict input, `model_validate_json()` for raw JSON strings. Both raise `ValidationError` on failure.

4. **Test file naming**: Files must start with `test_` and test functions must start with `test_`. Pytest discovers them automatically.

5. **Running a single test**: `uv run pytest tests/test_file.py::test_function -v`

6. **The `tests/__init__.py`** file already exists in this project (empty). Don't delete it — it's needed for Python to treat `tests/` as a package.
