
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

def main():
    render_meta_trend_page()

if __name__ == "__main__":
    main()
