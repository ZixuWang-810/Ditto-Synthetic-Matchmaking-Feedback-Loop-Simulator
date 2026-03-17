# Python Dependency Management with uv

## Adding Dependencies

```bash
# Add a package
uv add langgraph
uv add langchain-core langchain-ollama

# Add with version constraint
uv add "langgraph>=0.2"

# Add dev dependency
uv add --dev pytest
```

This updates `pyproject.toml` and `uv.lock` automatically.

## pyproject.toml Structure

```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "langgraph",
    "langchain-core",
    "langchain-ollama",
    "pydantic>=2.0",
]

[tool.uv]
package = false  # Not a distributable package

[tool.uv.sources]
# Local editable dependencies
tmb = { path = "./TMB", editable = true }
```

## Running Scripts

```bash
# Run a Python script (uses the project's venv)
uv run python main.py

# Run a module
uv run python -m pytest

# Run streamlit
uv run streamlit run app.py
```

## Syncing Environment

```bash
# Install all dependencies from lock file
uv sync

# After modifying pyproject.toml manually
uv lock
uv sync
```

## Gotchas

1. **`uv add` vs manual edit**: Prefer `uv add` — it resolves dependencies and updates the lock file. Manual edits to `pyproject.toml` require `uv lock` afterward.
2. **`package = false`**: This project uses `package = false` in `[tool.uv]`, meaning it's not installable as a package. Scripts run from the project root.
3. **Editable local deps**: The `tmb` dependency is local and editable. Don't remove it.
4. **Python version**: This project requires Python ≥3.13. Ensure compatibility.
