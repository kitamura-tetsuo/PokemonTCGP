
import streamlit as st
import logging
import sqlite3

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

try:
    from pokemontcgp.cache_snapshots import bind_snapshot, select_snapshot
    from pokemontcgp.data import verify_snapshot_binding
    from pokemontcgp.ui import render_meta_trend_page
    from pokemontcgp.ui_combinations import render_combinations_page
    from pokemontcgp.ui_comparison import render_comparison_page
    from pokemontcgp.ui_simulator import render_simulator_page
    from pokemontcgp.utils import is_local
except ModuleNotFoundError as exc:
    # A Git pull can replace app.py before the newly added package files arrive.
    # Do not hide missing third-party dependencies or render a misleading label.
    if exc.name == "pokemontcgp" or (exc.name or "").startswith("pokemontcgp."):
        logging.getLogger(__name__).warning("Application package update incomplete: %s", exc.name)
        st.info("Application update is in progress. Please retry shortly.")
        st.stop()
    raise

try:
    snapshot = select_snapshot()
    bind_snapshot(snapshot)
    verify_snapshot_binding(snapshot)
# Builtin exception bases remain stable when an application module is evicted.
# This guard covers only cache selection/binding, never UI or dependency imports.
except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
    st.error("Application data is temporarily unavailable. Please retry later.")
    logging.getLogger(__name__).error("Cache snapshot unavailable: %s", exc)
    st.stop()
if snapshot and snapshot.warning:
    st.warning(snapshot.warning)
if snapshot:
    st.caption("Data snapshot: " + snapshot.generation.removeprefix("cache-")[:12])

def main():
    st.sidebar.title("Navigation")
    
    # Sync with query param
    qp = st.query_params
    default_page = qp.get("page", "trends")
    
    pages = ["Metagame Trends", "Card Combinations", "Deck Comparison"]
    page_to_idx = {"trends": 0, "combinations": 1, "comparison": 2}
    
    local_env = is_local()
    if local_env:
        pages.append("Simulator")
        page_to_idx["simulator"] = 3
    
    idx = page_to_idx.get(default_page, 0)
    # Safety check for index if simulator was requested but is not available
    if idx >= len(pages):
        idx = 0
        
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
        if local_env:
            st.query_params["page"] = "simulator"
            render_simulator_page()
        else:
            st.query_params["page"] = "trends"
            st.rerun()

if __name__ == "__main__":
    main()
