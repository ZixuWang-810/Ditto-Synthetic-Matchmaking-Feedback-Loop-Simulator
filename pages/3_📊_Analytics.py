import streamlit as st
import pandas as pd
import plotly.express as px
from src.storage.mongo_client import get_mongo_storage

st.set_page_config(page_title="Analytics Dashboard", page_icon="📊", layout="wide")

st.title("📊 Observatory & Analytics")
st.markdown("Analyze the aggregate metrics and feedback extracted from matchmaking simulations.")

try:
    mongo = get_mongo_storage()
    stats = mongo.get_summary_stats()
except Exception as e:
    st.error(f"Cannot connect to MongoDB to fetch stats: {str(e)}")
    st.stop()

total_convs = stats.get("total_conversations", 0)
total_personas = stats.get("total_personas", 0)

# Always show persona stats even if no conversations yet
st.subheader("Population Overview")
pcol1, pcol2 = st.columns(2)
pcol1.metric("Total Personas", total_personas)

genders = stats.get("gender_distribution", {})
if genders:
    gender_str = ", ".join(f"{k}: {v}" for k, v in genders.items())
    pcol2.metric("Gender Breakdown", gender_str)

st.write("---")

if total_convs == 0:
    st.warning("No conversations recorded yet. Go to the Simulation Arena and run some matches!")
    
    # Still show gender pie chart if personas exist
    if genders:
        st.subheader("User Gender Distribution")
        df_gender = pd.DataFrame(list(genders.items()), columns=["Gender", "Count"])
        fig_genders = px.pie(df_gender, values="Count", names="Gender", hole=0.4,
                             title="Distribution of Persona Genders")
        st.plotly_chart(fig_genders)
    st.stop()

# ── Top Level KPIs ──
st.subheader("Conversation Metrics")
col1, col2, col3, col4 = st.columns(4)
matches_accepted = stats.get("matches_accepted", 0)
acceptance_rate = stats.get("acceptance_rate", 0) * 100

col1.metric("Total Simulations", total_convs)
col2.metric("Total Accepted", matches_accepted)
col3.metric("Acceptance Rate", f"{acceptance_rate:.1f}%")
col4.metric("Avg. Rounds to Accept", f"{stats.get('avg_rounds_to_acceptance', 0) or 0:.2f}")

st.write("---")

# ── Charts Row ──
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("Post-Date Rating Distribution")
    ratings = stats.get("rating_distribution", {})
    if ratings:
        df_ratings = pd.DataFrame(
            [{"Rating": str(k), "Count": v} for k, v in ratings.items()]
        )
        df_ratings = df_ratings.sort_values(by="Rating")
        
        fig_ratings = px.bar(df_ratings, x="Rating", y="Count", color="Rating", 
                             title="Frequency of Star Ratings",
                             color_discrete_sequence=px.colors.sequential.Teal)
        st.plotly_chart(fig_ratings)
    else:
        st.info("No rating data available yet.")

with col_chart2:
    st.subheader("User Gender Distribution")
    if genders:
        df_gender = pd.DataFrame(list(genders.items()), columns=["Gender", "Count"])
        fig_genders = px.pie(df_gender, values="Count", names="Gender", hole=0.4,
                             title="Distribution of Persona Genders")
        st.plotly_chart(fig_genders)
    else:
        st.info("No gender data available.")

st.write("---")

# ── Rejection Analytics ──
st.subheader("Historical Rejection Analytics")
st.markdown("Explore why users reject matches to improve RAG strategies in the future.")

try:
    rejection_stats = mongo.get_rejection_stats()  # returns list[dict] with {reason, count}
    
    if rejection_stats:
        total_rejections = sum(r.get("count", 0) for r in rejection_stats)
        st.metric("Total Rejection Events", total_rejections)
        
        st.markdown("#### Top Rejection Reasons")
        for r in rejection_stats:
            st.markdown(f"- 🗣️ \"{r['reason'][:200]}\" (×{r['count']})")
    else:
        st.info("No rejection data recorded yet.")
except Exception as e:
    st.warning(f"Rejection analytics not available: {e}")
