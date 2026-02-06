
import streamlit as st
import pandas as pd
import re
import html
import textwrap
import os
from src.data import (
    get_deck_details_by_signature, 
    get_clustered_daily_share_data, 
    get_period_statistics,
    get_cluster_mapping
)
from src.ui import (
    _get_set_periods, render_card_grid, _enrich_and_sort_cards
)
from src.simulator import convert_signature_to_deckgym, run_simulation, DECKS_DIR
from src.config import IMAGE_BASE_URL

def render_simulator_page():
    st.header("Deck Simulator")
    st.markdown("Simulate matches between your custom deck and the top meta decks using **DeckGym**.")

    # URL Params
    qp = st.query_params
    default_sigs = qp.get_all("sigs")
    default_period_code = qp.get("period", "All")

    # Controls
    with st.expander("Controls", expanded=True):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            sig_input = st.text_area(
                "Your Deck Signatures", 
                value=", ".join(default_sigs) if default_sigs else "",
                help="Enter signatures of decks you want to test. One per line or comma-separated."
            )
            sigs = [s.strip() for s in re.split(r'[,\n]', sig_input) if s.strip()]
            
        with col2:
            periods = _get_set_periods()
            period_options = [p["label"] for p in periods]
            period_idx = 0
            if default_period_code:
                for i, p in enumerate(periods):
                    if p["code"] == default_period_code:
                        period_idx = i
                        break
            
            selected_period_label = st.selectbox("Opponent Metagame Period", options=period_options, index=period_idx)
            selected_period = next(p for p in periods if p["label"] == selected_period_label)
            
            num_games = st.number_input("Games per Matchup", min_value=10, max_value=2000, value=100, step=10)

    # Sync URL
    st.query_params["sigs"] = sigs
    st.query_params["period"] = selected_period["code"]

    if not sigs:
        st.info("Enter deck signatures to begin.")
        return

    # Fetch Top Meta Decks as Opponents
    with st.spinner("Identifying top metagame decks..."):
        share_df = get_clustered_daily_share_data(
            start_date=selected_period["start"], 
            end_date=selected_period["end"]
        )
        period_stats = get_period_statistics(
            share_df, 
            start_date=selected_period["start"], 
            end_date=selected_period["end"], 
            clustered=True
        )
        
        sorted_clusters = sorted(
            period_stats.items(), 
            key=lambda x: x[1].get("avg_share", 0), 
            reverse=True
        )[:8]
        
        opponents = []
        sig_to_cluster, id_to_cluster = get_cluster_mapping()
        
        for label, info in sorted_clusters:
            try:
                cid = label.split("Cluster ")[1].split(")")[0]
                if cid in id_to_cluster:
                    rep_sig = id_to_cluster[cid]["representative_sig"]
                    name = id_to_cluster[cid].get("representative_name", "Unknown")
                    opponents.append({
                        "id": cid,
                        "name": name,
                        "rep_sig": rep_sig,
                        "label": label
                    })
            except: continue

    if not opponents:
        st.warning("Could not identify top metagame decks for this period.")
        return

    # Process Deck Details for user decks
    deck_details = get_deck_details_by_signature(sigs)

    st.subheader("Simulation Results")
    
    # Auto-run Logic
    current_params = {
        "sigs": sorted(sigs),
        "period": selected_period["code"],
        "num_games": num_games
    }
    
    last_params = st.session_state.get("simulator_last_params")
    should_run = last_params != current_params

    if should_run:
        results = {} # (user_sig, opponent_rep_sig) -> win_rate
        errors = [] # List of error messages
        
        progress_text = "Simulating matchups..."
        progress_bar = st.progress(0, text=progress_text)
        
        total_matchups = len(sigs) * len(opponents)
        current_matchup = 0
        
        try:
            for user_sig in sigs:
                # Convert user deck
                user_deck_path = convert_signature_to_deckgym(user_sig)
                
                for opp in opponents:
                    opp_sig = opp["rep_sig"]
                    opp_deck_path = convert_signature_to_deckgym(opp_sig)
                    
                    # Update progress
                    current_matchup += 1
                    progress_bar.progress(current_matchup / total_matchups, text=f"{progress_text} ({current_matchup}/{total_matchups})")
                    
                    # Run simulation
                    try:
                        wr = run_simulation(user_deck_path, opp_deck_path, num_games=num_games)
                        results[(user_sig, opp_sig)] = wr
                    except Exception as sim_err:
                        # st.warning(f"Failed to simulate {user_sig} vs {opp_sig}")
                        errors.append({
                            "matchup": f"{user_sig} vs {opp_sig}",
                            "error": str(sim_err)
                        })
                        results[(user_sig, opp_sig)] = None
                    
            st.session_state["simulator_results"] = results
            st.session_state["simulator_errors"] = errors
            st.session_state["simulator_last_params"] = current_params
            # st.success("Simulation complete!")
        except Exception as e:
            st.error(f"Critical error during simulation process: {e}")
        finally:
            progress_bar.empty()

    if "simulator_errors" in st.session_state and st.session_state["simulator_errors"]:
        with st.expander("Simulation Errors / Logs", expanded=False):
            for err in st.session_state["simulator_errors"]:
                st.error(f"**{err['matchup']}**")
                st.code(err["error"])

    if "simulator_results" in st.session_state:
        _render_simulation_matrix(sigs, opponents, deck_details, st.session_state["simulator_results"])

def _render_simulation_matrix(sigs, opponents, deck_details, results):
    st.divider()
    
    # Headers
    ECHARTS_COLORS = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc']
    sig_to_color = {sig: ECHARTS_COLORS[i % len(ECHARTS_COLORS)] for i, sig in enumerate(sigs)}

    table_html = textwrap.dedent(f"""
        <style>
        .matchup-matrix th, .matchup-matrix td {{ padding: 12px 8px; text-align: center; vertical-align: middle; min-width: 80px; }}
        .matchup-header-row th {{ background-color: #1a1c24; color: #888; text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; }}
        .matchup-side-col {{ background-color: #1a1c24; text-align: left !important; font-weight: 500; min-width: 160px !important; }}
        .matchup-cell {{ border-radius: 4px; font-weight: bold; font-size: 1.1em; }}
        </style>
        <div style="overflow-x: auto;">
        <table class="matchup-matrix">
            <thead>
                <tr class="matchup-header-row">
                    <th style="background: none;"></th>
    """).strip()
    
    for opp in opponents:
        table_html += f'<th>{opp["name"]}<br><span style="font-size: 0.8em; font-weight: normal;">{opp["rep_sig"]}</span></th>'
    table_html += "</tr></thead><tbody>"

    for sig in sigs:
        details = deck_details.get(sig, {})
        name = details.get("name", sig)
        color = sig_to_color.get(sig, "#ccc")
        
        table_html += textwrap.dedent(f"""
            <tr>
                <td class="matchup-side-col">
                    <div style="display: flex; align-items: center;">
                        <span style="width: 8px; height: 8px; border-radius: 50%; background-color: {color}; margin-right: 8px; display: inline-block;"></span>
                        <span>{name}</span>
                    </div>
                    <div style="font-size: 0.8em; opacity: 0.5; margin-left: 16px;">{sig}</div>
                </td>
        """).strip()
        
        for opp in opponents:
            wr = results.get((sig, opp["rep_sig"]))
            
            bg_color = "rgba(40, 42, 54, 0.8)"
            if wr is not None:
                if wr > 50:
                    alpha = min(0.8, 0.2 + (wr - 50) / 50)
                    bg_color = f"rgba(84, 112, 198, {alpha})"
                elif wr < 50:
                    alpha = min(0.8, 0.2 + (50 - wr) / 50)
                    bg_color = f"rgba(238, 102, 102, {alpha})"
                else:
                    bg_color = "rgba(255, 255, 255, 0.1)"
            
            wr_str = f"{wr:.1f}%" if wr is not None else "-"
            table_html += f'<td class="matchup-cell" style="background-color: {bg_color};">{wr_str}</td>'
            
        table_html += "</tr>"
        
    table_html += "</tbody></table></div>"
    st.markdown(table_html, unsafe_allow_html=True)
    
    # Optional: Display deck lists
    st.divider()
    st.subheader("Deck Lists (Cards)")
    for i, sig in enumerate(sigs):
        details = deck_details.get(sig)
        if details and "cards" in details:
            st.markdown(f"**{details.get('name')} ({sig})**")
            render_card_grid(details["cards"])
            if i < len(sigs) - 1:
                st.markdown("<br>", unsafe_allow_html=True)
