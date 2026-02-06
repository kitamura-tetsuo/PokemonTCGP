
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
from src.ui_comparison import render_comparison_page
from src.ui_simulator import render_simulator_page

def main():
    st.sidebar.title("Navigation")
    
    # Sync with query param
    qp = st.query_params
    default_page = qp.get("page", "trends")
    
    pages = ["Metagame Trends", "Card Combinations", "Deck Comparison", "Simulator"]
    page_to_idx = {"trends": 0, "combinations": 1, "comparison": 2, "simulator": 3}
    idx = page_to_idx.get(default_page, 0)
        
    page = st.sidebar.radio("Go to", pages, index=idx)
    
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
    elif page == "Deck Comparison":
        st.query_params["page"] = "comparison"
        render_comparison_page()
    elif page == "Simulator":
        st.query_params["page"] = "simulator"
        render_simulator_page()

if __name__ == "__main__":
    main()
