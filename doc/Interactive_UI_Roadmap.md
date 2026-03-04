# 🚀 Project Roadmap: Interactive Matchmaking Simulator UI

## 1. Project Analysis & Objectives
**Core Problem**: Command-line execution is opaque and difficult for non-technical stakeholders (or interviewers) to interact with or validate. We need a way to visualize the generation process and steer the simulation in real-time.
**Objective**: Build an interactive, web-based control panel using **Streamlit**. This UI will allow a user to visually configure, generate, and review Personas, manually trigger conversation simulations, and inspect the real-time chat logs and matchmaking logic.
**Target Output**: A multi-page Streamlit application that serves as the "Control Center" for the synthetic data generation pipeline.

## 2. Updated System Architecture (UI Focused)

We will adopt a **Multi-Page Streamlit App** architecture. The core backend components (LangGraph orchestrator, Pydantic models, MongoDB) remain the same, but they are now driven by UI events rather than CLI scripts.

### UI Architecture (Streamlit)
The application will be divided into three main pages/modules:

#### Page 1: 👤 Persona Studio (The "Character Creator")
*   **Purpose**: Interactive generation and editing of college student personas.
*   **Key Features**:
    *   **Generation Parameters**: Sliders and dropdowns to guide the LLM (e.g., Target Age Range, Specific Hobbies to include, "Strictness" of dealbreakers).
    *   **Batch Generation**: A button to "Generate N Personas" with a real-time progress bar.
    *   **Persona Gallery**: A data grid or card view displaying generated personas fetched from MongoDB.
    *   **Manual Edit/Override**: Ability to select a generated persona and manually tweak attributes (e.g., change "Height" or add a new "Dealbreaker") before saving it to the database.

#### Page 2: 💬 Simulation Arena (The "Matchmaking Lab")
*   **Purpose**: Orchestrating and visualizing the conversation between the Ditto Bot and a User Bot.
*   **Key Features**:
    *   **User Selection**: A dropdown to select a specific Persona from the database to act as the "User."
    *   **Simulation Configurator**: Toggles for injecting specific "Noise" (e.g., "Make user impatient", "Simulate a typo constraint") or selecting which RAG context (Baseline vs. Historical Feedback) the Ditto bot should use.
    *   **Live Chat View**: A WhatsApp/iMessage-style chat interface (`st.chat_message`) that updates in real-time as the LangGraph agents exchange messages.
    *   **"Brain" Inspector (Expandable UI)**: Next to the chat, an accordion view showing the *internal thought process* of the Ditto Bot (e.g., "Checking ChromaDB...", "Calculated Match Score: 0.85", "Decided to propose Match ID: 123").

#### Page 3: 📊 Observability & Analytics (The "Feedback Dashboard")
*   **Purpose**: Analyzing the results of batch simulations.
*   **Key Features**:
    *   Metrics dashboard comparing Rounds to Acceptance (Round 1 vs RAG-enhanced Round 2).
    *   Word clouds of rejection reasons.
    *   Export button to download specific conversation batches as JSONL.

---

## 3. Revised Development Phases & Milestones

### Step 1: Core Backend & Streamlit Scaffolding
*   **Tasks**:
    *   Set up the MongoDB connection and ChromaDB instances.
    *   Create the Pydantic schemas for Personas.
    *   Initialize the Streamlit multi-page app structure (`app.py`, `pages/1_Persona_Studio.py`, etc.).
*   **Milestone 1**: A functioning, containerized Streamlit app connecting to the local databases.

### Step 2: Building the Persona Studio UI
*   **Tasks**:
    *   Implement the LLM call for Persona generation (using LangChain).
    *   Build the Streamlit form for generation parameters.
    *   Build the interactive data table (`st.dataframe` or custom cards) to view and edit Personas fetched from MongoDB.
*   **Milestone 2**: Users can generate, view, edit, and delete Personas entirely through the web interface.

### Step 3: The Simulation Arena & Agent Integration
*   **Tasks**:
    *   Develop the LangGraph orchestrator linking the Ditto Bot and User Bot.
    *   Integrate LangGraph execution with Streamlit. *Crucial:* Use Streamlit callbacks or asynchronous generators to stream LangGraph output directly to the UI chat interface so it doesn't just "hang" while computing.
    *   Build the collapsible "thought process" inspector for the Ditto Bot.
*   **Milestone 3**: A user can select a Persona, click "Start Simulation", and watch the multi-turn chat unfold live on the screen, verifying the logic behind the scenes.

### Step 4: Batch Execution & Feedback RAG
*   **Tasks**:
    *   Add a "Batch Mode" to the Simulation Arena to run X interactions in the background (using threading or background tasks) to populate the database for analytics.
    *   Implement the RAG Feedback loop (extracting rejection reasons and querying ChromaDB).
    *   Add UI toggles to switch between "Baseline Bot" and "RAG-Enhanced Bot".
*   **Milestone 4**: The system can visually demonstrate how historical feedback changes the Ditto Bot's matching behavior in real-time.

### Step 5: Analytics Dashboard & Polish
*   **Tasks**:
    *   Complete the Page 3 (Analytics) views using `plotly` or `altair` within Streamlit.
    *   Ensure robust error handling in the UI (e.g., handling LLM API timeouts gracefully with `st.error`).
    *   Finalize styling and documentation.
*   **Milestone 5**: A polished, end-to-end interactive simulation environment ready for demonstration.

---

## 4. Practical Risk Analysis & Mitigation (UI Context)

| Risk | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **UI Blocking (Hanging App)** <br>*(LLM calls take 5-10 seconds; Streamlit reruns top-to-bottom on every interaction, freezing the UI).* | High | **Crucial Mitigation**: Heavy reliance on `st.cache_resource` for DB connections/LLM clients. Use `st.spinner` or asynchronous streaming mechanisms to keep the UI responsive while LangGraph nodes execute. Background tasks (like batch generation) should ideally use a queue (like Celery), but for a local prototype, Python `threading` combined with Streamlit's session state might suffice. |
| **State Management Chaos** <br>*(Streamlit loses variable state on re-runs).* | High | Store all non-persistent UI state (like selected target Persona, current chat history being viewed) strictly in `st.session_state`. Never rely on global Python variables. |
| **Visualizing Complex Agent State** <br>*(LangGraph states can become massive and unreadable).* | Medium | Create dedicated formatting functions that translate the raw LangGraph state dictionary into clean Markdown or JSON views mapped to Streamlit expanders (`with st.expander("Agent State"): st.json(...)`). |
