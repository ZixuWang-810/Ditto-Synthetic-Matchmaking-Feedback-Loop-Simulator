"""Centralized configuration for the Ditto Synthetic Matchmaking Simulator."""

import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PERSONAS_DIR = DATA_DIR / "personas"
CONVERSATIONS_DIR = DATA_DIR / "conversations"

# Ensure output directories exist
PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

# ── Ollama Settings ────────────────────────────────────────────────────────────
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# LLM model for structured output tasks (persona gen, scoring)
STRUCTURED_LLM_MODEL: str = os.getenv("STRUCTURED_LLM_MODEL", "llama3.2")

# LLM model for conversation generation
CONVERSATION_LLM_MODEL: str = os.getenv("CONVERSATION_LLM_MODEL", "llama3.2")

# Embedding model
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# ── Simulation Settings ───────────────────────────────────────────────────────
MAX_MATCH_ROUNDS: int = int(os.getenv("MAX_MATCH_ROUNDS", "6"))
DEFAULT_PERSONA_COUNT: int = int(os.getenv("DEFAULT_PERSONA_COUNT", "500"))
DEFAULT_CONVERSATION_COUNT: int = int(os.getenv("DEFAULT_CONVERSATION_COUNT", "300"))
MAX_CONVERSATION_TURNS: int = int(os.getenv("MAX_CONVERSATION_TURNS", "50"))
DROP_OFF_PROBABILITY: float = float(os.getenv("DROP_OFF_PROBABILITY", "0.15"))

# ── Persona Generation Settings ───────────────────────────────────────────────
PERSONA_BATCH_SIZE: int = int(os.getenv("PERSONA_BATCH_SIZE", "5"))

# ── Match Scoring Weights ─────────────────────────────────────────────────────
EMBEDDING_SCORE_WEIGHT: float = 0.4
LLM_SCORE_WEIGHT: float = 0.6

# ── MongoDB Settings ──────────────────────────────────────────────────────────
MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "ditto_simulator")
MONGODB_ENABLED: bool = os.getenv("MONGODB_ENABLED", "false").lower() in ("true", "1", "yes")
