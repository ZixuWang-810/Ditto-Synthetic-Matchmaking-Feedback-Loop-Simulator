# Ditto Project Architecture Reference

## Directory Structure

```
├── app.py                          # Streamlit main page
├── main.py                         # CLI entry point (generate-personas, run)
├── src/
│   ├── config.py                   # Centralized config (env vars, constants)
│   ├── llm/
│   │   └── client.py               # LLMClient — Ollama wrapper (chat, structured, embeddings)
│   ├── ditto_bot/
│   │   ├── agent.py                # DittoBot class — stateful matchmaking agent
│   │   ├── matcher.py              # MatchScorer — hybrid embedding + LLM scoring
│   │   └── prompts.py              # 5 prompt templates (system, match, rejection, date, feedback)
│   ├── customer_bot/
│   │   ├── agent.py                # CustomerBot — persona-driven user simulation
│   │   └── prompts.py              # Customer system prompt, noise injection, ghosting messages
│   ├── orchestrator/
│   │   ├── engine.py               # SimulationEngine — conversation loop orchestrator
│   │   └── logger.py               # ConversationLogger — JSONL + MongoDB persistence
│   ├── models/
│   │   ├── persona.py              # Persona, DatingPreferences, enums (Gender, DateType, etc.)
│   │   └── conversation.py         # ConversationLog, Turn, MatchPresented, SentimentLabel
│   ├── persona_generator/
│   │   └── generator.py            # PersonaGenerator — LLM-based persona creation
│   └── storage/
│       └── mongo_client.py         # MongoStorage — optional MongoDB persistence
├── pages/
│   ├── 1_👤_Persona_Studio.py
│   ├── 2_💬_Simulation_Arena.py
│   └── 3_📊_Analytics.py
├── data/
│   ├── personas/                   # JSONL persona pools
│   └── conversations/              # JSONL conversation logs
├── Gemini_Agents/                  # Experimental Gemini agent (DO NOT MODIFY)
└── Archived/                       # Archived Claude agent (DO NOT MODIFY)
```

## Key Classes & Their Responsibilities

### `DittoBot` (`src/ditto_bot/agent.py`)
- Manages `ConversationPhase` enum (GREETING → COLLECTING_PREFERENCES → PRESENTING_MATCH → HANDLING_REJECTION → DATE_PROPOSAL → POST_DATE_FEEDBACK → COMPLETED)
- State: `phase`, `current_round`, `user_preferences`, `rejection_reasons`, `shown_match_ids`, `current_match`, `accepted_match`, `conversation_history`, `_user_persona`
- Key methods: `start_conversation(persona)`, `process_message(user_msg)`, `_collect_preferences()`, `_present_match()`, `_handle_rejection()`, `_propose_date()`, `_collect_feedback()`
- Uses `MatchScorer` for scoring, prompt templates from `prompts.py`

### `MatchScorer` (`src/ditto_bot/matcher.py`)
- Hybrid scoring: 40% embedding cosine similarity + 60% LLM chain-of-thought
- `score_candidates(user, candidates, rejection_reasons, shown_ids)` → sorted `list[MatchResult]`
- Uses `nomic-embed-text` for embeddings, `llama3.2` for LLM reasoning
- Caches embeddings in `_embedding_cache`
- Applies hard filters (gender preference, age range) before scoring

### `CustomerBot` (`src/customer_bot/agent.py`)
- Persona-driven responses based on communication style and preference strictness
- Frustration model: 0.0 → 1.0, increases on bad matches
- ~10% noise injection (off-topic messages)
- Ghosting based on frustration + strictness
- NO access to Ditto Bot's internal scoring

### `SimulationEngine` (`src/orchestrator/engine.py`)
- Orchestrates DittoBot ↔ CustomerBot conversation loop
- Turn limit: `MAX_CONVERSATION_TURNS` (default 50)
- Drop-off simulation: `DROP_OFF_PROBABILITY` (default 15%)
- Logs to JSONL via `ConversationLogger`

### `LLMClient` (`src/llm/client.py`)
- Wraps `ollama.Client` for chat, structured output (JSON mode), and embeddings
- Factory functions: `get_llm_client()`, `get_conversation_client()`, `get_structured_client()`
- Lazy initialization of Ollama connection

## Config Constants (`src/config.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `CONVERSATION_LLM_MODEL` | `llama3.2` | Model for conversation |
| `STRUCTURED_LLM_MODEL` | `llama3.2` | Model for structured output |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `MAX_MATCH_ROUNDS` | `6` | Max match attempts per conversation |
| `MAX_CONVERSATION_TURNS` | `50` | Max turns per conversation |
| `DROP_OFF_PROBABILITY` | `0.15` | Chance of user dropping off |
| `EMBEDDING_SCORE_WEIGHT` | `0.4` | Weight for embedding similarity |
| `LLM_SCORE_WEIGHT` | `0.6` | Weight for LLM reasoning score |

## Data Flow

1. **Persona Generation**: LLM → Pydantic `Persona` → JSONL file + optional MongoDB
2. **Simulation**: Engine selects persona → DittoBot greets → loop(CustomerBot responds → DittoBot processes → phase transitions) → ConversationLog → JSONL + optional MongoDB
3. **Scoring**: User profile + candidate profiles → embedding similarity + LLM reasoning → `MatchResult` → presented to user
4. **UI**: Streamlit reads from MongoDB (personas, conversations) → displays in pages

## Consumers of DittoBot (files that import/use it)

1. `src/orchestrator/engine.py` — `SimulationEngine._run_single_conversation()`
2. `pages/2_💬_Simulation_Arena.py` — Streamlit live simulation
3. `main.py` — CLI (indirectly via SimulationEngine)

These are the files that need updating when DittoBot's interface changes.
