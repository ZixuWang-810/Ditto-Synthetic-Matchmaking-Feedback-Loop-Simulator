# JSONL I/O Patterns

## What is JSONL?

One JSON object per line. No wrapping array. Each line is independently parseable.

```
{"id": "1", "name": "Alice", "score": 0.8}
{"id": "2", "name": "Bob", "score": 0.6}
```

## Reading

```python
import json
from pathlib import Path

def read_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:  # Skip empty lines
                records.append(json.loads(line))
    return records
```

## With Pydantic Models

```python
from pydantic import BaseModel

def load_models(path: Path, model_class: type[BaseModel]) -> list[BaseModel]:
    models = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                models.append(model_class.model_validate_json(line))
    return models
```

## Writing / Appending (Append-Only Convention)

```python
def append_jsonl(path: Path, record: dict | BaseModel):
    """Append a single record. Creates file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        if isinstance(record, BaseModel):
            f.write(record.model_dump_json() + "\n")
        else:
            f.write(json.dumps(record) + "\n")

def write_jsonl(path: Path, records: list[dict | BaseModel]):
    """Write multiple records (overwrites file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            if isinstance(r, BaseModel):
                f.write(r.model_dump_json() + "\n")
            else:
                f.write(json.dumps(r) + "\n")
```

## Gotchas

1. **Append-only by convention**: In this project, JSONL files are append-only. Never overwrite existing records unless explicitly regenerating.
2. **Empty lines**: Always strip and skip empty lines when reading.
3. **Encoding**: Always use UTF-8. `open(path, "r", encoding="utf-8")`.
4. **Newline termination**: Every record MUST end with `\n`. Missing trailing newline causes the next append to merge with the last line.
5. **Pydantic enum serialization**: Use `model_dump_json()` which serializes enums as strings. Don't use `json.dumps(model.model_dump())` — that gives enum objects, not strings.
