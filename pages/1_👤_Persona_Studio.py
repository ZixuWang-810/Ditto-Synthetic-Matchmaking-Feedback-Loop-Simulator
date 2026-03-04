import streamlit as st
import pandas as pd
from src.storage.mongo_client import get_mongo_storage
from src.persona_generator.generator import PersonaGenerator
import logging
from src.config import DEFAULT_PERSONA_COUNT

st.set_page_config(page_title="Persona Studio", page_icon="👤", layout="wide")

st.title("👤 Persona Studio")
st.markdown("Generate synthetic profiles and inject them directly into your matchmaking ecosystem.")

mongo = get_mongo_storage()

# Metrics Top Summary
st.subheader("Population Metrics")
stats = mongo.get_summary_stats()
col1, col2, col3, col4 = st.columns(4)
total_personas = stats.get("total_personas", 0)
col1.metric("Total Personas", total_personas)
col2.metric("Male", stats.get("gender_distribution", {}).get("male", 0))
col3.metric("Female", stats.get("gender_distribution", {}).get("female", 0))
col4.metric("Non-Binary", stats.get("gender_distribution", {}).get("non_binary", 0))

st.write("---")

# Generator Interface
st.subheader("🛠️ Generate New Personas")

with st.expander("Configure Generator", expanded=True):
    with st.form("generation_form"):
        num_to_gen = st.slider("Number of Personas to Generate", min_value=1, max_value=50, value=3)
        sync_db = st.checkbox("Sync to MongoDB", value=True)
        
        submit_button = st.form_submit_button("Launch Generator 🚀")

if submit_button:
    generator = PersonaGenerator()
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    st.info(f"Generating {num_to_gen} personas. This may take a minute using local models...")
    
    with st.spinner("Warming up models..."):
        try:
            new_personas = generator.generate(
                count=num_to_gen, 
                mongo_enabled=sync_db
            )
            
            progress_bar.progress(100)
            status_text.success(f"✅ Successfully generated {len(new_personas)} personas!")
            
            # Show newly generated personas immediately
            if new_personas:
                st.subheader(f"🆕 Newly Generated ({len(new_personas)})")
                for p in new_personas:
                    p_dict = p.model_dump() if hasattr(p, 'model_dump') else p.dict()
                    with st.expander(f"**{p_dict.get('name', 'Unknown')}** — {p_dict.get('age', '?')}yo, {p_dict.get('gender', '?')}", expanded=False):
                        col_a, col_b = st.columns(2)
                        col_a.write(f"**Ethnicity:** {p_dict.get('ethnicity', 'N/A')}")
                        col_a.write(f"**Date Type:** {p_dict.get('date_type', 'N/A')}")
                        col_a.write(f"**Communication:** {p_dict.get('communication_style', 'N/A')}")
                        col_b.write(f"**Strictness:** {p_dict.get('preference_strictness', 'N/A')}")
                        col_b.write(f"**Hobbies:** {', '.join(p_dict.get('hobbies', []))}")
                        st.write(f"**Bio:** {p_dict.get('bio', 'N/A')}")
                        st.json(p_dict)
                    
        except Exception as e:
            st.error(f"Generation Failed: {e}")

st.write("---")

# Persona Gallery Database Viewer
st.subheader("📂 Persona Database Gallery")
all_personas = mongo._get_db().personas.find({}, {"_id": 0})
df = pd.DataFrame(list(all_personas))

if not df.empty:
    st.dataframe(
        df[["name", "age", "gender", "ethnicity", "date_type", "communication_style", "preference_strictness"]], 
        width='stretch',
        hide_index=True
    )
    
    st.markdown("#### Raw Detail Viewer")
    selected_name = st.selectbox("Select a persona to view deep details:", options=df["name"].tolist())
    if selected_name:
        detail_data = df[df["name"] == selected_name].iloc[0]
        st.json(detail_data.to_dict())
else:
    st.info("No personas found in the database. Generate some above!")
