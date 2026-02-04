
import streamlit as st
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

st.set_page_config(
    page_title="TCG Metagame Trends",
    page_icon="card_index",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.ui import render_meta_trend_page
from src.ui_combinations import render_combinations_page

def main():
    st.sidebar.title("Navigation")
    
    # Sync with query param
    qp = st.query_params
    default_page = qp.get("page", "trends")
    if default_page == "combinations":
        idx = 1
    else:
        idx = 0
        
    page = st.sidebar.radio("Go to", ["Metagame Trends", "Card Combinations"], index=idx)
    
    # Global Japanese toggle
    show_ja_default = qp.get("ja", "false").lower() == "true"
    show_ja = st.sidebar.toggle("Show Japanese Card Names", value=show_ja_default)
    st.session_state["show_japanese_toggle"] = show_ja
    st.query_params["ja"] = str(show_ja).lower()

    if page == "Metagame Trends":
        st.query_params["page"] = "trends"
        render_meta_trend_page()
    elif page == "Card Combinations":
        st.query_params["page"] = "combinations"
        render_combinations_page()

if __name__ == "__main__":
    main()
