# Pydantic v2 Patterns

## Installation

```bash
uv add pydantic
```

## Model Definition

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
import uuid

class Status(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"

class MyModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="Full name")
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    tags: list[str] = Field(default_factory=list)
    status: Status = Status.ACTIVE
    metadata: Optional[dict] = None
```

## Serialization / Deserialization

```python
# To dict
data = model.model_dump()
data_json_compat = model.model_dump(mode="json")  # Enums → strings, etc.

# To JSON string
json_str = model.model_dump_json()

# From dict
obj = MyModel.model_validate({"name": "Alice", "score": 0.8})

# From JSON string
obj = MyModel.model_validate_json('{"name": "Alice", "score": 0.8}')
```

## Validators

```python
from pydantic import field_validator, model_validator

class Persona(BaseModel):
    age: int
    degree_level: str

    @field_validator("age")
    @classmethod
    def check_age(cls, v):
        if v < 18 or v > 30:
            raise ValueError("Age must be 18-30")
        return v

    @model_validator(mode="after")
    def check_consistency(self):
        if self.age < 22 and self.degree_level in ("masters", "phd"):
            raise ValueError("Too young for graduate degree")
        return self
```

## Nested Models

```python
class DatingPreferences(BaseModel):
    preferred_genders: list[str]
    preferred_age_min: int = 18
    preferred_age_max: int = 30

class Persona(BaseModel):
    name: str
    dating_preferences: DatingPreferences

# Nested validation works automatically
p = Persona.model_validate({
    "name": "Alice",
    "dating_preferences": {"preferred_genders": ["male"], "preferred_age_min": 20}
})
```

## JSON Schema Generation

```python
schema = MyModel.model_json_schema()
# Returns a dict suitable for OpenAPI / LLM structured output
```

## Gotchas

1. **Pydantic v2 vs v1**: Use `model_validate()` not `parse_obj()`, `model_dump()` not `.dict()`, `model_dump_json()` not `.json()`.
2. **Enum serialization**: `model_dump()` returns enum members. Use `model_dump(mode="json")` to get string values.
3. **Optional fields**: `Optional[X]` means the field can be `None`, but it's still required unless you set `default=None`.
4. **Field defaults**: Mutable defaults must use `default_factory`: `Field(default_factory=list)`, never `Field(default=[])`.
5. **Extra fields**: By default, extra fields are ignored. Use `model_config = ConfigDict(extra="forbid")` to reject them.
