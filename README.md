# Ditto Synthetic Matchmaking Feedback Loop Simulator

A multi-agent simulation system that generates synthetic matchmaking conversations, mimicking Ditto AI's college dating platform. The system bootstraps a feedback loop by simulating realistic interactions between a matchmaking bot and persona-driven user bots.

## Architecture

```
┌───────────────────────────────────────────────────┐
│          Interactive Streamlit UI (app.py)        │
│👤 Persona Studio│💬Simulation Arena│📊 Analytics │
└──────────────────────┬────────────────────────────┘
                       │
┌──────────────────────▼────────────────────────────┐
│               Simulation Orchestrator             │
│  Manages conversation loops, logging, drop-offs   │
├───────────────────────────────────────────────────┤
│                                                   │
│  ┌──────────────────┐    ┌──────────────────────┐ │
│  │    Ditto Bot     │◄──►│   Customer Bot       │ │
│  │  (Matchmaker)    │    │  (Persona-driven)    │ │
│  │                  │    │                      │ │
│  │ • Match scoring  │    │ • Naturalistic chat  │ │
│  │ • Preference     │    │ • Ghosting/noise     │ │
│  │   tracking       │    │ • Frustration model  │ │
│  │ • Date proposal  │    │ • Post-date ratings  │ │
│  └────────┬─────────┘    └──────────────────────┘ │
│           │                                       │
│  ┌────────▼─────────┐                             │
│  │   Match Scorer   │                             │
│  │  Embedding (40%) │                             │
│  │  + LLM CoT (60%) │                             │
│  └──────────────────┘                             │
├───────────────────────────────────────────────────┤
│              Persona Generator                    │
│   Diverse synthetic college student profiles      │
└───────────────────────────────────────────────────┘
         ▼                        ▼
   persona_pool.jsonl      conversations_*.jsonl
         ▼                        ▼
 ┌──────────────────────────────────────────────────┐
 │         MongoDB Persistence Layer (Opt-in)       │
 └──────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| LLM Provider | Ollama (local models) |
| Conversation Generation | Llama 3.2 (via Ollama) |
| Structured Output / Scoring | Llama 3.2 (via Ollama) |
| Embeddings | Nomic Embed Text (via Ollama) |
| Data Models | Pydantic v2 |
| Data Persistence | JSONL & MongoDB (pymongo) |
| Interactive UI | Streamlit (multi-page app) |
| Visualization | Plotly + Pandas |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Environment

Create a `.env` file in the project root:
```env
# Optional: Set to true to always sync data to MongoDB by default
MONGODB_ENABLED=false
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=ditto_simulator

# To use Gemini instead of Ollama (optional)
# GEMINI_API_KEY=your_key_here
```

### 3. Install Ollama and Models (Local AI)

Download from [ollama.ai](https://ollama.ai), then pull the required models:
```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

### 4. Launch Interactive UI (Recommended)

The easiest way to use the system — a web-based control panel to generate personas, run simulations, and analyze results:

```bash
streamlit run app.py
```

The app runs at `http://localhost:8501` with three pages:
- **👤 Persona Studio** — Generate personas, view the gallery, inspect raw profiles
- **💬 Simulation Arena** — Select a persona (or 🎲 random), watch live DittoBot ↔ CustomerBot chat, auto-sync results to MongoDB
- **📊 Analytics** — View acceptance rates, rating distributions, and rejection analytics from MongoDB

### 5. CLI: Generate Personas

Generates detailed college student personas. Running multiple times **appends** new unique personas.

```bash
python main.py generate-personas --count 20 --preview

# Generate and sync directly to MongoDB
python main.py generate-personas --count 20 --mongo
```

### 6. CLI: Run Simulation

Simulate full matchmaking conversations between Ditto and the generated personas.

```bash
# Small test run (5 conversations)
python main.py simulate --num-conversations 5

# Run simulation and sync results to MongoDB
python main.py simulate --num-conversations 5 --mongo
```

### 7. MongoDB Commands (Optional)

```bash
# Bulk import all existing JSONL files into MongoDB
python main.py sync-to-mongo

# View summary statistics from MongoDB
python main.py mongo-stats
```

### 8. Validate Output

```bash
python main.py validate data/conversations/conversations_*.jsonl
```

## Project Structure

```
Ditto-Synthetic-Matchmaking-Feedback-Loop-Simulator/
│
├── app.py                          # Streamlit entry point (Control Center)
│
├── pages/                          # Streamlit multi-page UI
│   ├── 1_👤_Persona_Studio.py      # Persona generation & gallery
│   ├── 2_💬_Simulation_Arena.py    # Live chat simulation + MongoDB sync
│   └── 3_📊_Analytics.py           # Plotly dashboards for feedback analytics
│
├── main.py                         # CLI entry point (generate-personas, simulate, etc.)
│
├── src/
│   ├── config.py                   # Centralized configuration
│   ├── models/
│   │   ├── persona.py              # Persona Pydantic model
│   │   ├── conversation.py         # Conversation log schema
│   │   └── feedback.py             # Feedback models
│   ├── llm/
│   │   └── client.py               # Local-first LLM client (Ollama / Gemini)
│   ├── persona_generator/
│   │   └── generator.py            # Appending persona generation with diversity checks
│   ├── ditto_bot/
│   │   ├── agent.py                # Stateful matchmaking agent (phase-driven)
│   │   ├── matcher.py              # Hybrid match scorer (embedding + LLM CoT)
│   │   └── prompts.py              # System prompts
│   ├── customer_bot/
│   │   ├── agent.py                # Persona-driven user bot (ghosting, noise, frustration)
│   │   └── prompts.py              # User bot prompts
│   ├── orchestrator/
│   │   ├── engine.py               # Conversation simulation engine
│   │   └── logger.py               # JSONL logger (with MongoDB dual-write)
│   └── storage/
│       └── mongo_client.py         # MongoDB persistence and analytics layer
│
├── tests/                          # Pytest test suite (41 tests, mongomock)
│   ├── test_matcher.py
│   ├── test_models.py
│   ├── test_mongo.py
│   ├── test_orchestrator.py
│   └── test_persona_generator.py
│
├── doc/                            # Architecture and roadmap documents
├── data/                           # Generated JSONL output files
└── requirements.txt
```

## Conversation JSONL Schema

```json
{
  "conversation_id": "uuid",
  "persona": { "name": "...", "age": 21, ... },
  "turns": [
    { "role": "ditto|user", "content": "..." }
  ],
  "matches_presented": [
    { "match_id": "...", "round": 1, "accepted": true }
  ],
  "rejection_reasons": ["..."],
  "sentiment_trajectory": ["neutral", "frustrated", "satisfied"],
  "rounds_to_acceptance": 2,
  "post_date_rating": 4,
  "post_date_feedback": "Had a great time!"
}
```

## Testing

```bash
python -m pytest tests/ -v
```
*Note: MongoDB tests use `mongomock` and do not require a live database.*

## Configuration

All settings are configurable via environment variables in your `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL for the local Ollama instance |
| `CONVERSATION_LLM_MODEL` | `llama3.2` | Model for conversational turns |
| `STRUCTURED_LLM_MODEL` | `llama3.2` | Model for persona generation and scoring |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model for embeddings |
| `MONGODB_ENABLED` | `false` | Set to true to always sync to MongoDB |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MAX_MATCH_ROUNDS` | `6` | Max match attempts per conversation |
| `DROP_OFF_PROBABILITY` | `0.15` | Base probability of user ghosting |

## Future Work

- **RAG Feedback Analyzer**: ConversationLog schema supports embedding-based feedback retrieval
- **Batch Mode**: Run N conversations in the background from the Simulation Arena UI
- **Word Clouds**: Visualize rejection reasons as word clouds in the Analytics dashboard
