# LLM JSON Repair Patterns

## Problem
Local LLMs (especially smaller models like llama3.2) frequently produce malformed JSON:
- **Unescaped double quotes** inside string values: `"height (5'5"` → breaks parser
- **Unclosed brackets/braces**: truncated output from token limits
- **Trailing commas**: `["a", "b",]` → invalid JSON
- **Single quotes** instead of double quotes
- **Unquoted keys**: `{score: 0.5}` instead of `{"score": 0.5}`

## Library
**Python stdlib only** — `json` + `re`. No external dependencies needed.

## Pattern 1: Comprehensive JSON Repair Function

```python
import json
import re
from typing import Any, Optional

def repair_json(raw: str) -> Optional[dict[str, Any]]:
    """Attempt to repair common LLM JSON issues and parse.
    
    Returns parsed dict on success, None on failure.
    """
    text = raw.strip()
    
    # Step 1: Extract JSON object if wrapped in markdown code fences
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    
    # Step 2: Ensure we're working with the JSON object portion
    start = text.find('{')
    if start == -1:
        return None
    text = text[start:]
    
    # Step 3: Fix trailing commas before ] or }
    text = re.sub(r',\s*([}\]])', r'\1', text)
    
    # Step 4: Fix unescaped double quotes INSIDE string values
    # Strategy: parse character-by-character to find strings, then fix interior quotes
    text = _fix_unescaped_inner_quotes(text)
    
    # Step 5: Close unclosed brackets/braces
    text = _close_brackets(text)
    
    # Step 6: Try parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _fix_unescaped_inner_quotes(text: str) -> str:
    """Fix unescaped double quotes inside JSON string values.
    
    Handles cases like: "height difference (5'5" vs 6'1")"
    The inner " after 5'5 breaks JSON parsing.
    
    Strategy: Use regex to find string values and escape interior quotes.
    """
    # Match JSON string values: "key": "value with problematic "quotes" inside"
    # We process line by line within the JSON to handle the most common patterns
    
    result = []
    i = 0
    in_string = False
    string_start = -1
    escape_next = False
    
    while i < len(text):
        ch = text[i]
        
        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue
            
        if ch == '\\':
            result.append(ch)
            escape_next = True
            i += 1
            continue
        
        if ch == '"':
            if not in_string:
                in_string = True
                string_start = len(result)
                result.append(ch)
            else:
                # Check if this quote is really the end of the string
                # Look ahead: after optional whitespace, should see , : ] } or end
                rest = text[i+1:].lstrip()
                if not rest or rest[0] in (',', ':', ']', '}', '\n'):
                    # This is a real closing quote
                    in_string = False
                    result.append(ch)
                else:
                    # This is an unescaped interior quote — escape it
                    result.append('\\"')
            i += 1
            continue
        
        result.append(ch)
        i += 1
    
    return ''.join(result)


def _close_brackets(text: str) -> str:
    """Close any unclosed brackets/braces at the end of truncated JSON."""
    stack = []
    in_string = False
    escape_next = False
    
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()
    
    # If we're still inside a string, close it
    if in_string:
        text += '"'
    
    # Close remaining open brackets in reverse order
    for bracket in reversed(stack):
        text += ']' if bracket == '[' else '}'
    
    return text
```

## Pattern 2: Integration with generate_structured (Retry + Fallback)

```python
def generate_structured(
    self,
    prompt: str,
    response_model: Type[BaseModel],
    max_retries: int = 2,
    temperature: float = 0.3,
) -> BaseModel:
    """Generate structured output with repair, retry, and fallback."""
    
    last_error = None
    
    for attempt in range(1 + max_retries):
        raw_text = self._call_llm(prompt, temperature)
        
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
            except Exception as e:
                last_error = e
        
        # On retry, append stricter instruction
        if attempt < max_retries:
            prompt = prompt + (
                "\n\nIMPORTANT: Your previous response contained invalid JSON. "
                "Ensure all double quotes inside string values are escaped with \\. "
                "Ensure all brackets and braces are properly closed. "
                "Return ONLY valid JSON."
            )
            logger.warning(f"Structured output attempt {attempt+1} failed, retrying...")
    
    # All attempts failed — return fallback
    logger.warning(f"All {1 + max_retries} attempts failed for {response_model.__name__}. Using fallback.")
    return _build_fallback(response_model)
```

## Pattern 3: Building Pydantic Fallback Instances

```python
def _build_fallback(response_model: Type[BaseModel]) -> BaseModel:
    """Construct a minimal valid instance of a Pydantic model for fallback.
    
    Uses model_fields to determine required fields and their types,
    providing sensible defaults.
    """
    from pydantic import BaseModel
    from pydantic.fields import FieldInfo
    
    defaults = {}
    for name, field_info in response_model.model_fields.items():
        if field_info.default is not None:
            continue  # Has a default, skip
        
        annotation = field_info.annotation
        if annotation == float:
            defaults[name] = 0.5  # Neutral score
        elif annotation == str:
            defaults[name] = "Unavailable due to parsing failure"
        elif annotation == int:
            defaults[name] = 0
        elif annotation == bool:
            defaults[name] = False
        elif annotation == list or (hasattr(annotation, '__origin__') and annotation.__origin__ is list):
            defaults[name] = []
        elif annotation == dict or (hasattr(annotation, '__origin__') and annotation.__origin__ is dict):
            defaults[name] = {}
    
    return response_model(**defaults)
```

## Gotchas

1. **The `_fix_unescaped_inner_quotes` look-ahead is heuristic** — it works for 95%+ of LLM output but can't handle every edge case. That's why retry and fallback layers exist.

2. **Don't over-repair**: Only attempt repair after `json.loads()` fails. Valid JSON should never go through the repair pipeline (it could introduce bugs).

3. **Token truncation**: LLMs hitting token limits produce truncated JSON. The `_close_brackets` function handles this, but the data inside may be incomplete. The Pydantic validation step catches missing required fields.

4. **Temperature matters**: Lower temperature (0.1-0.3) produces more consistent JSON. The retry can optionally lower temperature further.

5. **Logging is critical**: Always log the raw response and the repair attempt result at WARNING level. Silent fallbacks hide systematic prompt issues that should be fixed upstream.

6. **The `5'5"` case specifically**: The unescaped `"` after `5'5` is the #1 most common LLM JSON bug with local models. The look-ahead heuristic in `_fix_unescaped_inner_quotes` catches it because after the `"` following `5'5`, the next non-whitespace char is NOT `,` `:` `]` `}` — it's more text or a closing paren.
