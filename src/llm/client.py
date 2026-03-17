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

        # Parse and validate against Pydantic model
        try:
            return response_schema.model_validate_json(raw_text)
        except Exception as e:
            # Try to extract JSON from the response if it contains extra text
            json_match = re.search(r'\{[\s\S]*\}', raw_text)
            if json_match:
                return response_schema.model_validate_json(json_match.group())
            raise ValueError(
                f"Failed to parse structured output: {e}\nRaw response: {raw_text[:500]}"
            )

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
