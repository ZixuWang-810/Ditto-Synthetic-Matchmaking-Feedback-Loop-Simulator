# PROJECT: Synthetic Matchmaking Feedback Loop Simulator

## Background

Reference: https://ditto.ai/

Ditto AI is a college dating startup that uses an agentic AI system to match students and arrange real-life dates — entirely through iMessage, with no swiping or manual chatting.

Their matchmaking pipeline includes multiple specialized agents:

- Analysis Agent  
- Matchmaking Agent  
- Date Simulation Agent  
- Scheduler Agent  

### Core Problem

Ditto needs user feedback data to improve matchmaking quality, but feedback data only accumulates after real deployments.

### Project Goal

This project bootstraps the feedback loop by:

- Synthetically generating realistic multi-turn conversations  
- Simulating interactions between:
  - A Ditto-style matchmaking bot  
  - Persona-driven user bots  
- Collecting structured feedback  
- Demonstrating measurable improvement across iterations  

---

## SYSTEM OVERVIEW

### 1. Persona Generator

Synthesizes realistic college student profiles using an LLM with structured output (Pydantic models).

#### Persona Attributes

Each persona includes:

- Name  
- Age  
- Gender  
- Ethnicity  
- Height  
- Hobbies & Interests  
- Degree Level  
- Date Type  
  - Life partner  
  - Serious relationship  
  - Casual dates  
  - New friends  
- Dating Preferences  
  - Who they want to date  
  - Preferred ethnicities  
  - Physical attraction criteria  

#### Target

Generate a pool of ~500 personas with:

- Realistic diversity  
- Varied communication styles  
- Different preference strictness  

---

### 2. Ditto Bot (Matchmaking Agent)

Mimics Ditto AI’s real product flow via a conversational LLM agent.

#### Responsibilities

- Collect user preferences  
- Present matches with justification  
- Propose date time & campus location  
- Collect post-date feedback  
- Offer re-matches  

#### Rejection Handling

On rejection:

- Ask for specific feedback  
- Incorporate feedback into future matches  

#### Match Selection Logic

- Retrieve candidate profiles  
- Score compatibility using:
  - Embedding cosine similarity  
  - LLM reasoning  
- Return top candidate with natural-language justification  

#### State Management

Maintain:

- Preference history  
- Rejection reasons  
- Previously shown matches  

---

### 3. User Bot (Persona-Driven User)

Acts as the simulated student user.

#### Behavior Characteristics

- Naturalistic responses  
- Varied interaction styles:
  - Ghosting  
  - Enthusiasm  
  - Contradictory feedback  

#### Post-Date Feedback

After accepted matches:

- Rating (1–5)  
- Qualitative feedback  

#### Noise Injection

Include realistic distractions:

- Bug reports  
- Random questions  
- Casual conversation  

---

### 4. Simulation Orchestrator

Manages conversation simulations between Ditto Bot and Customer Bot pairs.

#### Simulation Rules

- Parallel or sequential runs  
- Max 6 match rounds per conversation  
- Simulates user drop-off  

### Logging Schema (JSONL)

```json
{
  "conversation_id": "uuid",
  "persona": { ... },
  "turns": [
    { "role": "ditto|user", "content": "..." }
  ],
  "matches_presented": [
    { "match_id": "...", "round": int, "accepted": bool }
  ],
  "rejection_reasons": [ "..." ],
  "sentiment_trajectory": [ "neutral|frustrated|satisfied" ],
  "rounds_to_acceptance": int,
  "post_date_rating": int | null
}
```

#### Target Output

Generate 300–500 conversations

---

## FUTURE WORK COMPONENTS
### Note: Former work needs to be designed to be compatible with the future work components.

### 5. Conversation Persistence Layer (MongoDB)

All conversations persisted in real-time.

#### Why MongoDB

- Dynamic schema evolution  
- Efficient querying  
- Horizontal scalability  

#### Role

Single source of truth for:

- Chat history  
- User behavior  
- Feedback patterns  

---

### 6. Feedback Analyzer (RAG + Evaluation Pipeline)

Extracts structured insights from conversations.

#### RAG Pipeline

- Store feedback embeddings in ChromaDB  
- Retrieve relevant feedback  
- Inject into Ditto Bot prompts  

#### Pattern Analysis

Identify:

- Frequent rejection reasons  
- Dealbreaker violations  
- Trait mismatches  

#### Improvement Metrics

Compare:

- Round 1: No feedback context  
- Round 2: RAG-injected feedback  

Metrics:

- Average rounds_to_acceptance  
- Average post_date_rating  

---

### 7. Observability Dashboard (Streamlit)

Visualizations:

- Conversation statistics  
- Sentiment trajectories  
- Rejection reason word clouds  
- Round comparisons  

---

## SKILLS & TOOLS
Reference: https://ditto.ai/careers?ashby_jid=f4cbce81-94bf-44cb-a2fc-4dcd001175e1   
Assume this project is built for preparing an interview for the software engineer intern role in Ditto. Try best to implement skills and tools they required on this page and align with the job description (Make this project similar with what I will do if I get the offer and start to work as a software engineer intern in Ditto).

### Languages

- Python (Primary)  
- TypeScript (Optional)

### LLM Calls

- Claude  
- Gemini  
- GPT  
- Prefer local models for cost efficiency (For example: when generate conversations)

### Multi-Agent Orchestration

- LangGraph / CrewAI  

### Prompt Engineering

- Structured Output (Pydantic / JSON Mode)  
- Chain-of-thought for match justification  

### Evaluation

LLM-as-judge scoring:

- Personality compatibility  
- Interest overlap  
- Value alignment  
- Communication style fit  

---

## STORAGE ARCHITECTURE

- MongoDB → Source of Truth  
- ChromaDB → Semantic Search  
- SQLite → Relational Metadata  
- JSONL → Portable Backup  

---

## DELIVERABLES

### 1. Runnable Python Codebase

/persona_generator  
/ditto_bot  
/customer_bot  
/orchestrator  
/feedback_analyzer  
/dashboard

### 2. Synthetic Conversation Logs

- 300–500 JSONL files  

### 3. Feedback Analysis Report

Includes:

- Top 10 rejection reasons  
- Round comparisons  
- Sentiment distribution  

### 4. Streamlit Dashboard

### 5. README

Explaining:

- Architecture  
- Execution steps  
- Demonstrated improvements  

---

## CONSTRAINTS & NOTES

- Use environment variables for API keys  
- Optimize LLM costs  
- Avoid logic leakage  

### Critical Rule

Customer Bot must NOT access Ditto Bot internal scoring logic.

- Conversations must feel naturalistic  
- Avoid repetitive phrasing  
