"""Unified LLM client abstraction using Ollama local models exclusively.
Supports chat, structured output (JSON mode), and embeddings."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Type

import numpy as np
from pydantic import BaseModel

from src import config

logger = logging.getLogger(__name__)


# ── JSON Repair Helpers ───────────────────────────────────────────────────────

def _fix_unescaped_inner_quotes(text: str) -> str:
    """Fix unescaped double quotes inside JSON string values.

    Handles cases like: "height difference (5'5" vs 6'1")"
    The inner " after 5'5 breaks JSON parsing.

    Strategy: Use a character-by-character state machine that tracks whether
    we're inside a JSON string. When it detects a '"' that is NOT preceded by
    '\\' and is NOT a structural string delimiter (i.e., it's followed by
    characters that don't match ':', ',', '}', ']', or whitespace + any of
    those), escape it to '\\"'.
    """
    result = []
    i = 0
    in_string = False
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
                result.append(ch)
            else:
                # Check if this quote is really the end of the string.
                # Look ahead: after optional whitespace, should see , : ] } or end.
                rest = text[i + 1:].lstrip()
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


def repair_json(raw: str) -> Optional[dict]:
    """Attempt to repair common LLM JSON issues and parse.

    Fixes applied in order:
    1. Strip markdown code fences (```json ... ```)
    2. Find the JSON object start (first '{')
    3. Fix trailing commas before ] or }
    4. Fix unescaped double quotes inside string values
    5. Close unclosed brackets/braces
    5b. Fix trailing commas again (may be exposed after bracket closing)
    6. Attempt json.loads() — return dict on success, None on failure

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
    text = _fix_unescaped_inner_quotes(text)

    # Step 5: Close unclosed brackets/braces
    text = _close_brackets(text)

    # Step 5b: Fix trailing commas again — closing brackets may have exposed
    # a trailing comma that was previously at the end of the truncated string
    # (e.g. '{"a": 1, "b": [1, 2,' → after close → '{"a": 1, "b": [1, 2,]}')
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Step 6: Try parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── LLM Client ────────────────────────────────────────────────────────────────

class LLMClient:
    """LLM client using Ollama local models for all operations:
    chat, structured output (JSON mode), and embeddings."""

    # Class-level flag: shared across all instances so the model is only pulled
    # once per process, regardless of how many LLMClient instances are created.
    _embedding_model_verified: bool = False

    def __init__(
        self,
        model: str | None = None,
        embedding_model: str | None = None,
    ):
        self.model = model or config.CONVERSATION_LLM_MODEL
        self.embedding_model = embedding_model or config.EMBEDDING_MODEL
        self._client = None

    # ── Provider Initialization (Lazy) ────────────────────────────────────

    def _get_client(self):
        """Lazy-initialize the Ollama client."""
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=config.OLLAMA_BASE_URL)
            except ImportError:
                raise RuntimeError(
                    "Ollama package not installed. Run: pip install ollama\n"
                    "Also ensure Ollama is running: https://ollama.ai"
                )
        return self._client

    # ── Chat Completion ───────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.8,
        **kwargs,
    ) -> str:
        """Send a chat completion request and return the response text."""
        client = self._get_client()
        model = model or self.model

        ollama_messages = []
        if system_prompt:
            ollama_messages.append({"role": "system", "content": system_prompt})
        ollama_messages.extend(messages)

        response = client.chat(
            model=model,
            messages=ollama_messages,
            options={"temperature": temperature},
        )

        return response["message"]["content"]

    # ── Structured Output (Ollama JSON mode) ──────────────────────────────

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.7,
    ) -> BaseModel:
        """Generate a response conforming to a Pydantic schema using Ollama JSON mode.

        Converts the schema to a human-readable example (local models understand
        examples far better than raw JSON schema definitions).

        On parse failure, applies a repair-then-retry pipeline:
        1. Attempt repair_json() on the raw response and validate.
        2. If repair fails, retry the LLM call once with a correction prompt.
        3. On retry, attempt direct parse, then repair again.
        4. If all attempts fail, raise ValueError with the original raw text.
        """
        client = self._get_client()
        model = model or self.model

        # Build a human-readable example instead of raw JSON schema
        example = self._schema_to_example(response_schema.model_json_schema())
        example_json = json.dumps(example, indent=2)

        full_prompt = (
            f"{prompt}\n\n"
            f"Respond with ONLY a JSON object in exactly this format:\n"
            f"{example_json}\n\n"
            f"Fill in real values. Output ONLY valid JSON, no commentary."
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": full_prompt})

        response = client.chat(
            model=model,
            messages=messages,
            format="json",
            options={"temperature": temperature},
        )

        raw_text = response["message"]["content"]

        # ── Attempt 1: Direct parse ───────────────────────────────────────
        try:
            return response_schema.model_validate_json(raw_text)
        except Exception as original_exc:
            # Try to extract JSON from the response if it contains extra text
            json_match = re.search(r'\{[\s\S]*\}', raw_text)
            if json_match:
                try:
                    return response_schema.model_validate_json(json_match.group())
                except Exception:
                    pass

            original_error = ValueError(
                f"Failed to parse structured output: {original_exc}\n"
                f"Raw response: {raw_text[:500]}"
            )

        # ── Attempt 2: Repair the raw response ───────────────────────────
        logger.warning(
            f"Structured parse failed for {response_schema.__name__}, "
            f"attempting JSON repair... (raw[:200]: {raw_text[:200]!r})"
        )
        repaired = repair_json(raw_text)
        if repaired is not None:
            try:
                result = response_schema.model_validate(repaired)
                logger.warning(
                    f"JSON repair succeeded for {response_schema.__name__}."
                )
                return result
            except Exception as repair_val_exc:
                logger.warning(
                    f"JSON repair produced a dict but validation failed for "
                    f"{response_schema.__name__}: {repair_val_exc}"
                )
        else:
            logger.warning(
                f"JSON repair returned None for {response_schema.__name__}."
            )

        # ── Attempt 3: Retry the LLM call with a correction prompt ───────
        logger.warning(
            f"Retrying LLM call for {response_schema.__name__} with correction "
            f"prompt (temperature=0.2)..."
        )
        retry_messages = messages + [
            {"role": "assistant", "content": raw_text},
            {
                "role": "user",
                "content": (
                    "Your previous response had invalid JSON. "
                    "Return ONLY valid JSON matching the schema. No extra text."
                ),
            },
        ]
        retry_response = client.chat(
            model=model,
            messages=retry_messages,
            format="json",
            options={"temperature": 0.2},
        )
        retry_raw = retry_response["message"]["content"]

        # Attempt 3a: Direct parse of retry response
        try:
            result = response_schema.model_validate_json(retry_raw)
            logger.warning(
                f"Retry direct parse succeeded for {response_schema.__name__}."
            )
            return result
        except Exception:
            pass

        # Attempt 3b: Repair the retry response
        retry_repaired = repair_json(retry_raw)
        if retry_repaired is not None:
            try:
                result = response_schema.model_validate(retry_repaired)
                logger.warning(
                    f"Retry repair succeeded for {response_schema.__name__}."
                )
                return result
            except Exception as retry_repair_val_exc:
                logger.warning(
                    f"Retry repair produced a dict but validation failed for "
                    f"{response_schema.__name__}: {retry_repair_val_exc}"
                )
        else:
            logger.warning(
                f"Retry repair returned None for {response_schema.__name__}. "
                f"retry_raw[:200]: {retry_raw[:200]!r}"
            )

        # ── All attempts exhausted — raise original error ─────────────────
        raise original_error

    @staticmethod
    def _schema_to_example(schema: dict) -> dict:
        """Convert a JSON schema to a concrete example dict.
        
        Local models understand concrete examples much better than abstract
        JSON schema definitions with type/description/properties.
        """
        def _resolve(prop: dict, name: str = "") -> Any:
            prop_type = prop.get("type", "string")
            
            if prop_type == "object":
                properties = prop.get("properties", {})
                result = {}
                for key, val in properties.items():
                    result[key] = _resolve(val, key)
                return result
            elif prop_type == "array":
                items = prop.get("items", {"type": "string"})
                return [_resolve(items, name)]
            elif prop_type == "number":
                # Use sensible defaults based on field name
                if "score" in name.lower():
                    return 0.65
                return 0.5
            elif prop_type == "integer":
                return 1
            elif prop_type == "boolean":
                return True
            elif prop_type == "string":
                # Generate a helpful placeholder based on field name
                placeholders = {
                    "justification": "Brief explanation of the reasoning",
                    "reason": "Brief explanation",
                    "feedback": "Qualitative description",
                    "content": "Text content here",
                    "name": "Example Name",
                }
                for key, val in placeholders.items():
                    if key in name.lower():
                        return val
                return "example text"
            else:
                return "example"
        
        properties = schema.get("properties", {})
        result = {}
        for key, val in properties.items():
            # Skip internal fields like 'id'
            result[key] = _resolve(val, key)
        return result

    # ── Embeddings (Ollama) ───────────────────────────────────────────────

    def get_embedding(self, text: str) -> list[float]:
        """Generate an embedding for a single text string using Ollama.

        Implements a lazy auto-pull pattern:
        - Fast path: if the embedding model has already been verified this
          process, call client.embed() directly.
        - Slow path: on the first call (or if a 404/model-not-found error is
          caught), attempt to pull the model automatically, then retry once.
        - If the pull itself fails, log a WARNING and re-raise the original
          exception so the caller's fallback logic (e.g. LLM-only scoring in
          matcher.py) can handle it gracefully.

        The class-level ``_embedding_model_verified`` flag ensures the pull
        only happens once per process regardless of how many LLMClient
        instances exist.
        """
        client = self._get_client()
        model = self.embedding_model

        # ── Fast path ────────────────────────────────────────────────────
        if LLMClient._embedding_model_verified:
            response = client.embed(model=model, input=text)
            return response["embeddings"][0]

        # ── Slow path: first call or model not yet verified ───────────────
        try:
            response = client.embed(model=model, input=text)
            # Success on first attempt — mark as verified for all future calls
            LLMClient._embedding_model_verified = True
            return response["embeddings"][0]

        except Exception as original_exc:
            error_str = str(original_exc).lower()
            is_model_not_found = "not found" in error_str or "404" in error_str

            if not is_model_not_found:
                # Non-404 error (e.g. Ollama not running) — re-raise immediately
                raise

            # 404 / model-not-found: attempt auto-pull then retry once
            logger.info(
                f"Pulling embedding model '{model}'... this may take a moment"
            )
            try:
                client.pull(model=model)
                logger.info(f"Successfully pulled embedding model '{model}'")
                LLMClient._embedding_model_verified = True
                # Retry the embed call exactly once after a successful pull
                response = client.embed(model=model, input=text)
                return response["embeddings"][0]

            except Exception as pull_exc:
                logger.warning(
                    f"Failed to pull embedding model '{model}': {pull_exc}. "
                    "Embedding scoring will be unavailable; "
                    "falling back to LLM-only scoring."
                )
                # Re-raise the *original* embed exception so the existing
                # fallback in matcher.py (_compute_embedding_scores_safe)
                # catches it and degrades gracefully to LLM-only scoring.
                raise original_exc

    def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts using Ollama.

        Delegates each text to ``get_embedding()`` so the lazy auto-pull
        logic is applied consistently for all callers (including matcher.py).
        """
        # If a non-default model is requested, call the Ollama client directly
        # (the auto-pull logic in get_embedding is tied to self.embedding_model).
        if model is not None and model != self.embedding_model:
            client = self._get_client()
            embeddings = []
            for text in texts:
                result = client.embed(model=model, input=text)
                embeddings.append(result["embeddings"][0])
            return embeddings

        # Default path: use get_embedding() for auto-pull support
        return [self.get_embedding(text) for text in texts]

    def cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm == 0:
            return 0.0
        return float(dot / norm)


# ── Factory Functions ─────────────────────────────────────────────────────────

def get_llm_client(
    model: str | None = None,
) -> LLMClient:
    """Create an LLM client with the specified or default model."""
    return LLMClient(model=model)


def get_conversation_client() -> LLMClient:
    """Create an LLM client configured for conversation generation."""
    return LLMClient(model=config.CONVERSATION_LLM_MODEL)


def get_structured_client() -> LLMClient:
    """Create an LLM client configured for structured output tasks."""
    return LLMClient(model=config.STRUCTURED_LLM_MODEL)
