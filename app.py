import streamlit as st
import os

# Configure the main page properties
st.set_page_config(
    page_title="Ditto Sandbox Simulator",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for UI styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E1E1E;
        margin-bottom: 0px;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #4B4B4B;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #F8F9FA;
        border-radius: 10px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
    }
</style>
""", unsafe_allow_html=True)

# Main Dashboard Content
st.markdown('<div class="main-header">🤖 Ditto Sandbox Simulator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Control Center for Synthetic Matchmaking & Conversation Generation</div>', unsafe_allow_html=True)

st.write("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    ### 👤 Persona Studio
    Create, manage, and inspect realistic college student personas.
    * Generate highly diverse synthetic user profiles
    * Control dating preferences and attributes
    * Build the population for your simulation experiments
    
    👉 **[Go to Persona Studio](/Persona_Studio)**
    """)

with col2:
    st.markdown("""
    ### 💬 Simulation Arena
    Run autonomous, multi-agent matchmaking conversations.
    * Chat in real-time between Ditto and synthetic users
    * Inject noise and view Ditto's internal thought process
    * Run batch simulation evaluations
    
    👉 **[Go to Simulation Arena](/Simulation_Arena)**
    """)

with col3:
    st.markdown("""
    ### 📊 Analytics
    Observe aggregate metrics from conversation logs.
    * Acceptance & Drop-off rates
    * Sentiment Analysis
    * Match rejection tracking
    
    👉 **[Go to Analytics](/Analytics)**
    """)

st.write("---")
st.info("💡 **Tip**: Use the sidebar to navigate between operational modes. All generated data is stored securely in your local MongoDB instance/JSONL files.")

# Check for database connectivity
try:
    from src.storage.mongo_client import get_mongo_storage
    mongo = get_mongo_storage()
    stats = mongo.get_summary_stats()
    st.success(f"✅ Connected to MongoDB `{mongo._get_db().name}` (Loaded {stats.get('total_personas', 0)} Personas)")
except Exception as e:
    st.warning("⚠️ Could not connect to MongoDB. Using JSONL backend only.")
