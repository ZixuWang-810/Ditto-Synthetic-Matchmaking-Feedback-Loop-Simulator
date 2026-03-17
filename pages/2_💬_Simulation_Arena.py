import streamlit as st
import time
import random
from src.storage.mongo_client import get_mongo_storage
from src.llm.client import get_llm_client
from src.ditto_bot.graph import build_ditto_graph, DittoState
from src.customer_bot.agent import CustomerBot
from src.models.conversation import ConversationLog, Turn, TurnRole, MatchPresented, SentimentLabel
from src import config
from langchain_core.messages import AIMessage, HumanMessage

st.set_page_config(page_title="Simulation Arena", page_icon="💬", layout="wide")

st.title("💬 Simulation Arena")
st.markdown("Watch Ditto try to match a user in real-time. Pick a synthetic persona to simulate the conversation.")

mongo = get_mongo_storage()

# Fetch personas using the proper loader that remaps _id → id
try:
    all_personas = mongo.load_personas()
except Exception as e:
    st.error(f"Failed to load personas from MongoDB: {e}")
    all_personas = []

if not all_personas:
    st.warning("No personas found! Go to the Persona Studio to generate some.")
    st.stop()

# Layout
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Configure Simulation")
    
    # 1. User Selection — index-based with random option
    persona_labels = ["🎲 Random"] + [f"{p.name} ({p.age}, {p.gender.value})" for p in all_personas]
    selected_idx = st.selectbox(
        "Select User Persona:",
        options=range(len(persona_labels)),
        format_func=lambda i: persona_labels[i]
    )
    
    # Resolve random selection
    if selected_idx == 0:
        actual_idx = random.randint(0, len(all_personas) - 1)
        selected_persona = all_personas[actual_idx]
        st.info(f"🎲 Randomly selected: **{selected_persona.name}**")
    else:
        selected_persona = all_personas[selected_idx - 1]
    
    st.info(f"**Target:** {selected_persona.date_type.value}\n\n**Style:** {selected_persona.communication_style.value}")
    with st.expander("View Full Bio Settings"):
        st.write(selected_persona.bio)
        st.write(f"**Strictness:** {selected_persona.preference_strictness.value}")
        
    st.write("---")
    
    # 2. Config overrides
    st.markdown("#### Engine Overrides")
    max_turns = st.slider("Max Conversation Turns", min_value=4, max_value=20, value=10)
    sync_mongo = st.checkbox("Sync to MongoDB", value=True)
    
    start_sim = st.button("Start Simulation ▶️", type="primary")

with col2:
    st.subheader("Live Console")
    
    if start_sim:
        chat_container = st.container(height=500)
        thought_container = st.expander("🧠 Ditto Thought Process (Phases & Matches)", expanded=True)
        
        # Initialize agents using the real APIs
        llm = get_llm_client()
        ditto_graph = build_ditto_graph()
        customer = CustomerBot(persona=selected_persona, llm_client=llm)
        
        # Initialize conversation log for MongoDB persistence
        log = ConversationLog(persona=selected_persona)
        turns_log: list[Turn] = []
        sentiment_trajectory = [SentimentLabel.NEUTRAL]
        post_date_rating = None
        post_date_feedback_text = None

        # ── Build initial DittoState ──────────────────────────────────────────
        state: DittoState = {
            "messages": [],
            "user_persona": selected_persona.model_dump(),
            "persona_pool": [p.model_dump() for p in all_personas],
            "phase": "greeting",
            "user_preferences": [],
            "rejection_reasons": [],
            "shown_match_ids": [],
            "current_match": None,
            "accepted_match": None,
            "current_round": 0,
            "max_rounds": config.MAX_MATCH_ROUNDS,
            "llm_model": llm.model,
            "embedding_model": llm.embedding_model,
        }
        
        with st.spinner("Initializing Conversation..."):
            # Phase 1: Invoke graph to get the greeting
            state = ditto_graph.invoke(state)

            # Extract the AI greeting from the last message
            greeting = ""
            for msg in reversed(state["messages"]):
                if isinstance(msg, AIMessage):
                    greeting = msg.content
                    break

            turns_log.append(Turn(role=TurnRole.DITTO, content=greeting))
            
            with chat_container:
                with st.chat_message("ai", avatar="🤖"):
                    st.markdown(greeting)
            
            with thought_container:
                st.markdown(f"**Phase:** `{state.get('phase', 'greeting')}`")
                st.divider()
            
            # Phase 2: User shares preferences
            user_response = customer.respond(greeting)
            turns_log.append(Turn(role=TurnRole.USER, content=user_response))
            
            with chat_container:
                with st.chat_message("user", avatar="👤"):
                    st.markdown(user_response)
            
            # Check for immediate drop-off
            if customer.has_dropped_off:
                log.dropped_off = True
                log.turns = turns_log
                log.sentiment_trajectory = sentiment_trajectory
                if sync_mongo:
                    mongo.insert_conversation(log)
                    st.toast("📦 Conversation synced to MongoDB")
                with chat_container:
                    st.warning("👻 User ghosted immediately!")
                st.stop()
            
            # Phase 3: Conversation loop
            turn_count = 0
            
            while state.get("phase", "completed") != "completed" and turn_count < max_turns:
                turn_count += 1
                time.sleep(0.5)
                
                with st.spinner(f"Ditto is thinking (Turn {turn_count})..."):
                    # Add the latest user message to state and invoke the graph
                    state["messages"] = list(state["messages"]) + [HumanMessage(content=user_response)]
                    state = ditto_graph.invoke(state)
                
                # Extract Ditto's response from the last AIMessage
                ditto_response = ""
                for msg in reversed(state["messages"]):
                    if isinstance(msg, AIMessage):
                        ditto_response = msg.content
                        break

                turns_log.append(Turn(role=TurnRole.DITTO, content=ditto_response))
                
                with chat_container:
                    with st.chat_message("ai", avatar="🤖"):
                        st.markdown(ditto_response)
                
                current_phase = state.get("phase", "completed")

                with thought_container:
                    st.markdown(f"**Turn {turn_count} | Phase:** `{current_phase}`")
                    current_match = state.get("current_match")
                    if current_match:
                        candidate = current_match.get("candidate", {})
                        st.markdown(f"- Match: `{candidate.get('name', 'Unknown')}`")
                        st.markdown(f"- Justification: _{current_match.get('justification', '')}_")
                    st.divider()
                
                if current_phase == "completed":
                    break
                
                # Customer responds based on conversation phase
                with st.spinner("User is responding..."):
                    if current_phase == "presenting_match":
                        # Record the match
                        current_match = state.get("current_match")
                        if current_match:
                            match_candidate = current_match.get("candidate", {})
                            match_presented = MatchPresented(
                                match_id=match_candidate.get("id", ""),
                                match_name=match_candidate.get("name", "Unknown"),
                                round=state.get("current_round", turn_count),
                                accepted=False,
                                justification=current_match.get("justification", ""),
                            )
                            log.matches_presented.append(match_presented)
                        
                        user_response = customer.evaluate_match(ditto_response)
                        
                        # Check if accepted
                        lower = user_response.lower()
                        accepted = any(w in lower for w in [
                            "yes", "sure", "sounds good", "let's do it", "okay", "down",
                            "interested", "love", "great", "accept", "cool",
                        ])
                        
                        if accepted and log.matches_presented:
                            log.matches_presented[-1].accepted = True
                            log.rounds_to_acceptance = state.get("current_round", turn_count)
                            sentiment_trajectory.append(SentimentLabel.EXCITED)
                        else:
                            log.rejection_reasons.append(user_response)
                            sentiment_trajectory.append(
                                SentimentLabel.FRUSTRATED if customer.frustration_level > 0.4
                                else SentimentLabel.NEUTRAL
                            )
                        
                        with thought_container:
                            st.markdown(f"**Match {'✅ ACCEPTED' if accepted else '❌ REJECTED'}**")
                    
                    elif current_phase == "post_date_feedback":
                        feedback_response, rating = customer.give_post_date_feedback(ditto_response)
                        user_response = feedback_response
                        post_date_rating = rating
                        post_date_feedback_text = feedback_response
                        sentiment_trajectory.append(
                            SentimentLabel.SATISFIED if rating >= 3 else SentimentLabel.DISAPPOINTED
                        )
                        
                        with thought_container:
                            st.info(f"**Post-Date Rating:** {rating}/5 ⭐")
                    
                    else:
                        user_response = customer.respond(ditto_response)
                
                turns_log.append(Turn(role=TurnRole.USER, content=user_response))
                
                with chat_container:
                    with st.chat_message("user", avatar="👤"):
                        st.markdown(user_response)
                
                # Check for drop-off
                if customer.has_dropped_off:
                    log.dropped_off = True
                    sentiment_trajectory.append(SentimentLabel.FRUSTRATED)
                    with chat_container:
                        st.warning("👻 User dropped off!")
                    break
            
            # ── Finalize & Persist ──
            log.turns = turns_log
            log.sentiment_trajectory = sentiment_trajectory
            log.total_rounds = state.get("current_round", turn_count)
            if post_date_rating is not None:
                log.post_date_rating = post_date_rating
            if post_date_feedback_text is not None:
                log.post_date_feedback = post_date_feedback_text
            
            # Sync to MongoDB
            if sync_mongo:
                try:
                    mongo.insert_conversation(log)
                    st.toast("📦 Conversation synced to MongoDB!", icon="✅")
                except Exception as e:
                    st.error(f"Failed to sync conversation: {e}")
            
            # Final status
            if state.get("phase", "") == "completed":
                with chat_container:
                    st.success("🎉 Conversation completed successfully!")
            elif turn_count >= max_turns:
                with chat_container:
                    st.error("❌ Max turns reached.")
