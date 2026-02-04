
import json
import os
from datetime import datetime, timedelta
import logging
import re
import textwrap
import pandas as pd
import streamlit as st
from collections import Counter

from src.data import (
    get_daily_share_data, get_deck_details, get_all_card_names, 
    get_match_history, enrich_card_data, get_clustered_daily_share_data,
    get_cluster_details, get_cluster_mapping, get_card_info_by_name,
    load_enriched_sets, get_daily_winrate_for_decks
)
from src.visualizations import create_echarts_stacked_area, display_chart, create_echarts_line_comparison
from src.config import IMAGE_BASE_URL
from src.utils import format_deck_name

def get_display_name(c):
    show_ja = st.session_state.get("show_japanese_toggle", False)
    if show_ja and c.get("name_ja"):
        return c.get("name_ja")
    return c.get("name", "")

def format_card_name(card_id):
    """Format a card ID like 'A1_1' into 'Name (SetID-Number)'."""
    if not card_id:
        return ""
    
    from src.data import get_card_info_by_id
    info = get_card_info_by_id(card_id)
    if not info:
        return card_id
        
    english_name = info.get("name", "Unknown")
    show_ja = st.session_state.get("show_japanese_toggle", False)
    name = english_name
    if show_ja:
        from src.data import get_card_name
        ja_name = info.get("name_ja") or get_card_name(english_name, lang="ja")
        if ja_name and ja_name != english_name:
            name = ja_name
            
    c_set = info.get("set", "")
    c_num = info.get("number", "")
    return f"{name} ({c_set}-{c_num})"


logger = logging.getLogger(__name__)

@st.cache_data(ttl=3600)
def _get_card_type_map():
    # In this implementation, card types are already enriched in data.py
    # But for sorting, we need the order.
    pass

def _enrich_and_sort_cards(cards):
    """Sort cards by Pokemon > Item > Tool > Stadium > Supporter. Cards are already enriched in data.py."""
    type_order = {
        "Pokemon": 0,
        "Goods": 1,
        "Item": 2,
        "Stadium": 3,
        "Support": 4,
        "Unknown": 5,
    }

    # Sort: type_order, then name
    # We use .get("type") directly as it's already enriched/normalized
    cards.sort(
        key=lambda x: (type_order.get(x.get("type", "Unknown"), 5), x.get("name", ""))
    )
    return cards

def sort_card_ids(card_ids):
    """Sort card IDs based on deck list order (Pokemon > Trainer > Energy)."""
    if not card_ids:
        return []
    
    from src.data import get_card_info_by_id
    enriched = []
    for cid in card_ids:
        info = get_card_info_by_id(cid)
        if info:
            # We need a dict with 'type' and 'name' for _enrich_and_sort_cards
            enriched.append({
                "id": cid,
                "type": info.get("type", "Unknown"),
                "name": info.get("name", "")
            })
        else:
            enriched.append({
                "id": cid,
                "type": "Unknown",
                "name": cid
            })
            
    sorted_enriched = _enrich_and_sort_cards(enriched)
    return [item["id"] for item in sorted_enriched]

def render_card_grid(cards):
    """Render a responsive grid of card images."""
    if not cards:
        return
    
    enriched_cards = _enrich_and_sort_cards(cards)
    
    all_copies = []
    for c in enriched_cards:
        count = c.get("count", 1)
        for _ in range(count):
            all_copies.append(c)

    if not all_copies:
        return

    html = '<div class="card-grid">'
    for c in all_copies:
        c_set = c.get("set", "")
        c_num = c.get("number", "")
        try: p_num = f"{int(c_num):03d}"
        except: p_num = c_num
        img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
        name = get_display_name(c)
        html += f'<div class="card-item"><img src="{img}" class="card-img" title="{name}" alt="{name}" onerror="this.style.display=\'none\'"></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

def render_filtered_cards(card_ids):
    """Render small card images for a list of card IDs (SetID_Number)."""
    if not card_ids:
        return
    
    css = """
    <style>
    .filter-card-container { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; margin-bottom: 10px; }
    .filter-card { width: 45px; height: auto; border-radius: 4px; border: 1px solid rgba(255,255,255,0.1); }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
    
    from src.data import get_card_info_by_id
    h = '<div class="filter-card-container">'
    for card_id in card_ids:
        info = get_card_info_by_id(card_id)
        if info:
            c_set = info.get("set", "")
            c_num = info.get("number", "")
            try: p_num = f"{int(c_num):03d}"
            except: p_num = c_num
            img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
            h += f'<img src="{img}" class="filter-card" title="{format_card_name(card_id)}">'
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

@st.cache_data(ttl=600)
def _get_cached_trend_data(selected_cards, exclude_cards, window, start_date=None, end_date=None, standard_only=False, clustered=False):
    # Call the data layer
    if clustered:
        return get_clustered_daily_share_data(
            card_filters=selected_cards, 
            exclude_cards=exclude_cards, 
            window=window,
            start_date=start_date,
            end_date=end_date,
            standard_only=standard_only
        )
    else:
        return get_daily_share_data(
            card_filters=selected_cards, 
            exclude_cards=exclude_cards, 
            window=window,
            start_date=start_date,
            end_date=end_date,
            standard_only=standard_only
        )

def _get_set_periods():
    try:
        enriched_sets = load_enriched_sets()
        show_ja = st.session_state.get("show_japanese_toggle", False)
        
        processed_periods = []
        for i, s in enumerate(reversed(enriched_sets)): # Original logic was ascending then reversing, enriched_sets is already descending
            # To match the end date calculation logic, let's process them in chronological order
            pass
        
        # Actually it's cleaner to just redo the list processing
        chronological_sets = sorted(enriched_sets, key=lambda x: x.get("releaseDate", "9999-99-99"))
        
        processed_periods = []
        for i in range(len(chronological_sets)):
            s = chronological_sets[i]
            start = s.get("releaseDate")
            
            # Use name based on toggle
            name = s.get("name_ja") if show_ja else s.get("name_en")
            if not name:
                name = s.get("code")
            
            end = None
            if i < len(chronological_sets) - 1:
                end_dt = datetime.strptime(chronological_sets[i+1]["releaseDate"], "%Y-%m-%d") - timedelta(days=1)
                end = end_dt.strftime("%Y-%m-%d")
            
            label = f"{name} ({start} ~ {end if end else 'Now'})"
            processed_periods.append({"label": label, "start": start, "end": end, "name": name, "release": start, "code": s.get("code")})
        
        # Newest first
        processed_periods.sort(key=lambda x: x["release"], reverse=True)
        
        return [{"label": "All", "start": None, "end": None, "code": "All"}] + processed_periods
    except Exception as e:
        logger.error(f"Error loading set periods: {e}")
        return []

def render_meta_trend_page():
    st.header("Metagame Trends")
    st.markdown(
        "Visualize the evolution of the metagame over time. You can filter by specific cards to see how decks containing them perform."
    )

    # Sidebar / Controls
    with st.expander("Controls", expanded=True):
        col1, col2, col3 = st.columns(3)
        from src.data import get_all_card_ids
        all_card_ids = get_all_card_ids()
        periods = _get_set_periods()
        
        # Read from query params
        q_params = st.query_params
        default_cards = q_params.get_all("cards")
        default_exclude = q_params.get_all("exclude")
        default_period_label = q_params.get("period", "")
        default_clustered = q_params.get("clustered", "false").lower() == "true"
        try:
            default_window = int(q_params.get("window", 7))
        except:
            default_window = 7

        with col1:
            selected_cards = st.multiselect("Filter by Cards (AND)", options=all_card_ids, default=[c for c in default_cards if c in all_card_ids], format_func=format_card_name)
            render_filtered_cards(selected_cards)

            exclude_cards = st.multiselect("Exclude Cards (NOT)", options=all_card_ids, default=[c for c in default_exclude if c in all_card_ids], format_func=format_card_name)
            render_filtered_cards(exclude_cards)

        with col2:
            period_options = [p["label"] for p in periods]
            # Default to the latest set (index 1) if available, otherwise "All" (index 0)
            
            # Find index of default period label via code lookup
            period_idx = 1 if len(period_options) > 1 else 0
            if default_period_label:
                # Try finding by code
                for i, p in enumerate(periods):
                    if p["code"] == default_period_label:
                        period_idx = i
                        break
                else:
                    # Fallback to label match if code didn't work (for old URLs)
                    try:
                        period_idx = period_options.index(default_period_label)
                    except ValueError:
                        pass

            selected_period_label = st.selectbox("Aggregation Period", options=period_options, index=period_idx)
            selected_period = next(p for p in periods if p["label"] == selected_period_label)
            
            standard_only = selected_period["label"] != "All"
            clustered = st.toggle("Clustered Metagame Trends", value=default_clustered)

        with col3:
            window = st.slider(
                "Moving Average Window (Days)", min_value=1, max_value=14, value=default_window
            )

        # Update query params on change
        # Note: Streamlit's st.query_params handles multiple values for same key automatically with get_all/set_all
        # but for simple assignment, it replaces.
        st.query_params["cards"] = selected_cards
        st.query_params["exclude"] = exclude_cards
        st.query_params["period"] = selected_period["code"]
        st.query_params["window"] = window
        st.query_params["clustered"] = str(clustered).lower()

    # Fetch Data
    with st.spinner("Aggregating daily share data..."):
        try:
            df = _get_cached_trend_data(
                selected_cards, 
                exclude_cards, 
                window,
                start_date=selected_period["start"],
                end_date=selected_period["end"],
                standard_only=standard_only,
                clustered=clustered
            )
            
            # If filtered, fetch global data for reference (Diffs)
            global_df = None
            if selected_cards or exclude_cards:
                global_df = _get_cached_trend_data(
                    None, 
                    None, 
                    window,
                    start_date=selected_period["start"],
                    end_date=selected_period["end"],
                    standard_only=standard_only,
                    clustered=clustered
                )
        except Exception as e:
            st.error(f"Error fetching trend data: {e}")
            df = pd.DataFrame()

    if df.empty:
        st.warning("No data found for the selected filters.")
        return

    # shared CSS for tooltips and tables
    css = """
    .meta-table { font-family: sans-serif; font-size: 14px; width: 100%; color: #eee; border-collapse: collapse; margin-top: 10px; }
    .meta-header-row { font-weight: bold; border-bottom: 2px solid rgba(255,255,255,0.2); background-color: #1a1c24; }
    .meta-table th, .meta-table td { padding: 12px 15px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .meta-table th { text-align: left; position: sticky; top: 0; background-color: #0e1117; z-index: 100; color: #888; text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px; }
    .meta-row-link { 
        display: table-row; cursor: pointer; transition: background 0.15s; text-decoration: none; color: inherit;
    }
    .meta-row-link:hover { background-color: rgba(255,255,255,0.05); }
    .header-link { cursor: pointer; user-select: none; transition: color 0.2s; white-space: nowrap; }
    .header-link:hover { color: #fff; }
    .sort-indicator { margin-left: 6px; font-family: monospace; font-size: 12px; transition: opacity 0.2s; }
    .tooltip { position: relative; display: inline-block; width: 100%; }
    .tooltip .tooltiptext {
        visibility: hidden; width: 340px; background-color: #1e1e1e; color: #fff;
        text-align: center; border-radius: 8px; padding: 10px; position: absolute;
        z-index: 1000; bottom: 125%; left: 0;
        opacity: 0; transition: opacity 0.3s, transform 0.3s; 
        transform: translateY(10px);
        box-shadow: 0 10px 30px rgba(0,0,0,0.6);
        pointer-events: none;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .tooltip:hover .tooltiptext { visibility: visible; opacity: 1; transform: translateY(0); }
    .tooltip-card { width: 60px; height: auto; border-radius: 4px; background: #333; transition: transform 0.2s; }
    .tooltip-card:hover { transform: scale(1.1); z-index: 10; }
    .tooltip-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 2px; justify-items: center; }
    .diff-img { height: 40px; width: auto; border-radius: 3px; margin: 1px; }
    .archetype-name { font-weight: 600; color: #1ed760; text-decoration: none; display: inline-block; }
    .archetype-name:hover { text-decoration: underline; color: #1fdf64; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
    .card-grid {
        display: grid;
        grid-template-columns: repeat(10, 1fr);
        gap: 8px;
        margin-top: 10px;
    }
    .card-item {
        width: 100%;
        position: relative;
    }
    .card-img {
        width: 100%;
        height: auto;
        border-radius: 4px;
        display: block;
        transition: transform 0.2s;
    }
    .card-img:hover {
        transform: scale(1.05);
        z-index: 10;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    @media (max-width: 1200px) {
        .card-grid { grid-template-columns: repeat(8, 1fr); }
    }
    @media (max-width: 900px) {
        .card-grid { grid-template-columns: repeat(6, 1fr); }
    }
    @media (max-width: 600px) {
        .card-grid { grid-template-columns: repeat(4, 1fr); }
    }
    """
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

    # Check for Drill-Down
    query_params = st.query_params
    selected_sig = query_params.get("deck_sig", None)
    selected_cluster_id = query_params.get("cluster_id", None)
    
    if selected_cluster_id:
        _render_cluster_detail_view(selected_cluster_id, selected_period)
        return
    elif selected_sig:
        _render_deck_detail_view(selected_sig, selected_period)
        return

    # Visualization
    latest_shares = df.iloc[-1].sort_values(ascending=False)
    MAX_ARCHS = 12
    n_rows = len(df)
    
    if len(df.columns) <= MAX_ARCHS:
        df_display = df
        top_archetypes = df.columns.tolist()
    else:
        # Define 5 time points: Start, 1/4, 2/4, 3/4, End
        indices = [0, n_rows // 4, n_rows // 2, (3 * n_rows) // 4, n_rows - 1]
        # Ensure indices are unique and within range
        indices = sorted(list(set([max(0, min(i, n_rows - 1)) for i in indices])))
        
        ranked_at_points = [df.iloc[idx].sort_values(ascending=False) for idx in indices]
        selected_archetypes = []
        
        # 1. Top 2 decks from each point
        for rank in range(2):
            for point_data in ranked_at_points:
                if rank < len(point_data):
                    arch = point_data.index[rank]
                    if arch not in selected_archetypes and point_data[arch] > 0:
                        selected_archetypes.append(arch)
                        if len(selected_archetypes) >= MAX_ARCHS:
                            break
            if len(selected_archetypes) >= MAX_ARCHS:
                break
        
        # 2. Fill remaining until 12
        if len(selected_archetypes) < MAX_ARCHS:
            for rank in range(2, len(df.columns)):
                found_at_this_rank = False
                for point_data in ranked_at_points:
                    if rank < len(point_data):
                        found_at_this_rank = True
                        arch = point_data.index[rank]
                        if arch not in selected_archetypes and point_data[arch] > 0:
                            selected_archetypes.append(arch)
                            if len(selected_archetypes) >= MAX_ARCHS:
                                break
                if len(selected_archetypes) >= MAX_ARCHS or not found_at_this_rank:
                    break
        
        top_archetypes = selected_archetypes
        other_archetypes = [c for c in df.columns if c not in top_archetypes]
        df_display = df[top_archetypes].copy()
        if other_archetypes:
            df_display["Others"] = df[other_archetypes].sum(axis=1)

    # Build statistics and details for both chart tooltips and table
    from src.data import get_period_statistics
    s_start, s_end = selected_period["start"], selected_period["end"]
    
    stats_map = get_period_statistics(
        df, 
        start_date=s_start, 
        end_date=s_end, 
        clustered=clustered
    )
    
    # details_map for chart: label -> {name, stats, cards}
    # cards are already enriched in data.py via get_period_statistics
    details_map = {label: info["deck_info"] for label, info in stats_map.items()}

    fig_options = create_echarts_stacked_area(
        df_display, details_map=details_map, title=f"Daily Metagame Share (window={window}d)"
    )
    if fig_options:
        # Define click event to return series name
        events = {
            "click": "function(params) { return params.seriesName; }"
        }
        clicked_series = display_chart(fig_options, height="450px", events=events)
        
        if clicked_series:
            # Extract sig or cluster id
            if "Cluster" in clicked_series:
                cid = clicked_series.split("Cluster ")[1].split(")")[0]
                st.query_params["cluster_id"] = cid
            else:
                match = re.search(r"\((\w+)\)$", clicked_series)
                if match:
                    sig = match.group(1)
                    st.query_params["deck_sig"] = sig
            st.query_params["page"] = "trends"
            st.rerun()

    # Table
    st.subheader("Metagame Statistics")
    st.caption("Click headers to sort instantly. Latest Share is relative to total metagame today.")

    # Prepare Data for Table
    # Show diffs always if there is data (against the #1 archetype)
    is_filtered = selected_cards is not None and len(selected_cards) > 0
    show_diffs = not df.empty and is_filtered
    # st.write(f"DEBUG: selected_cards={selected_cards}, show_diffs={show_diffs}")
    latest_shares = df.iloc[-1].to_dict() if not df.empty else {}
    rows_data = []
    
    for label, info in stats_map.items():
        share = latest_shares.get(label, 0.0)
        avg_share = info["avg_share"]
        stats = info["stats"]
        deck_info = info["deck_info"]
        
        # Calculate WR
        w, l, t = stats.get("wins", 0), stats.get("losses", 0), stats.get("ties", 0)
        mtch = w + l + t
        wr = (w / mtch * 100) if mtch > 0 else 0.0
        
        # Determine ID (sig or cluster_id)
        sig = None
        cid = None
        if clustered and "Cluster" in label:
            cid = label.split("Cluster ")[1].split(")")[0]
        else:
            match = re.search(r"\((\w+)\)$", label)
            sig = match.group(1) if match else None

        rows_data.append({
            "sig": sig,
            "cid": cid,
            "full_name": label,
            "name": label.split("(")[0].strip(),
            "share": share,
            "period_share": avg_share,
            "wr": wr,
            "players": stats.get("players", 0),
            "matches": mtch,
            "deck_info": deck_info
        })

    if not rows_data:
        st.info("No data available for the selected period.")
        return

    # Sort options for table
    sort_options = {
        "share": "Latest Share (Window)",
        "period_share": "Period Avg Share",
        "wr": "Win Rate (Period)",
        "players": "Total Players (Period)",
        "matches": "Total Matches (Period)"
    }
    # Read from query params
    q_sort = st.query_params.get("sort", "period_share")
    q_order = st.query_params.get("order", "desc")
    
    # Sort mapping
    sort_key_map = {
        "name": lambda x: x["name"].lower(),
        "share": lambda x: x["share"],
        "period_share": lambda x: x["period_share"],
        "wr": lambda x: x["wr"],
        "players": lambda x: x["players"],
        "matches": lambda x: x["matches"]
    }
    
    if q_sort in sort_key_map:
        rows_data.sort(key=sort_key_map[q_sort], reverse=(q_order == "desc"))

    # --- Win Rate Chart Section ---
    wr_identifiers = set()
    
    # 1. From Share Chart
    # df_display columns are formatted as "Name (Sig)" or "Name (Cluster ID)"
    if not df_display.empty:
        for col in df_display.columns:
            if "Cluster" in col:
                # Format: Name (Cluster ID)
                try:
                    cid = col.split("Cluster ")[1].split(")")[0]
                    wr_identifiers.add(cid)
                except: pass
            else:
                match = re.search(r"\(([\da-f]{8})\)$", col)
                if match:
                    wr_identifiers.add(match.group(1))
    
    # 2. From Table Top 10
    for row in rows_data[:10]:
        if row.get("cid"):
            wr_identifiers.add(str(row["cid"]))
        elif row.get("sig"):
            wr_identifiers.add(str(row["sig"]))
            
    if wr_identifiers:
        with st.spinner("Calculating win rates..."):
            wr_df = get_daily_winrate_for_decks(
                list(wr_identifiers),
                window=window,
                start_date=selected_period["start"],
                end_date=selected_period["end"],
                clustered=clustered
            )
            
            if not wr_df.empty:
                st.subheader("Daily Win Rate")
                wr_options = create_echarts_line_comparison(wr_df, details_map=details_map, title=f"Daily Win Rate (window={window}d)", y_axis_label="Win Rate (%)")
                
                # Define click event to return series name
                events = {
                    "click": "function(params) { return params.seriesName; }"
                }
                
                clicked_series_wr = display_chart(wr_options, height="400px", events=events)
                if clicked_series_wr:
                    # Extract sig or cluster id
                    target_sig = None
                    target_cid = None
                    
                    if "Cluster" in clicked_series_wr:
                        try:
                            target_cid = clicked_series_wr.split("Cluster ")[1].split(")")[0]
                        except: pass
                    else:
                        match = re.search(r"\(([\da-f]{8})\)$", clicked_series_wr)
                        if match:
                            target_sig = match.group(1)
                    
                    if target_cid:
                         st.query_params["cluster_id"] = target_cid
                         st.query_params["page"] = "trends"
                         st.rerun()
                    elif target_sig:
                         st.query_params["deck_sig"] = target_sig
                         st.query_params["page"] = "trends"
                         st.rerun()
                st.divider()
    # -----------------------------

    def get_sort_link(col_name):
        new_order = "desc"
        if q_sort == col_name:
            new_order = "asc" if q_order == "desc" else "desc"
        
        # Build query string from current params but override sort/order
        # Use get_all for all keys to preserve multi-value params like 'cards'
        params = {k: st.query_params.get_all(k) for k in st.query_params}
        params["sort"] = [col_name]
        params["order"] = [new_order]
        
        from urllib.parse import urlencode
        return "?" + urlencode(params, doseq=True)

    def get_sort_indicator(col_name):
        if q_sort == col_name:
            return " ▲" if q_order == "asc" else " ▼"
        return " ▴▾"

    def get_header_style(col_name):
        if q_sort == col_name:
            return 'style="color: #1ed760;"'
        return ''

    diff_headers = ""
    diff_headers = ""
    if show_diffs:
        diff_headers = '<th class="header-link">REMOVED</th><th class="header-link">ADDED</th>'

    html = textwrap.dedent(
        f"""
<table class="meta-table">
<thead>
<tr class="meta-header-row">
<th class="header-link" {get_header_style('name')}>
    <a href="{get_sort_link('name')}" target="_self" style="color: inherit; text-decoration: none;">ARCHETYPE<span class="sort-indicator">{get_sort_indicator('name')}</span></a>
</th>
{diff_headers}
<th class="header-link" {get_header_style('share')} style="text-align: right;">
    <a href="{get_sort_link('share')}" target="_self" style="color: inherit; text-decoration: none;">LATEST<br>SHARE <span class="sort-indicator">{get_sort_indicator('share')}</span></a>
</th>
<th class="header-link" {get_header_style('period_share')} style="text-align: right;">
    <a href="{get_sort_link('period_share')}" target="_self" style="color: inherit; text-decoration: none;">PERIOD<br>SHARE <span class="sort-indicator">{get_sort_indicator('period_share')}</span></a>
</th>
<th class="header-link" {get_header_style('wr')} style="text-align: right;">
    <a href="{get_sort_link('wr')}" target="_self" style="color: inherit; text-decoration: none;">PERIOD<br>WIN RATE<span class="sort-indicator">{get_sort_indicator('wr')}</span></a>
</th>
<th class="header-link" {get_header_style('players')} style="text-align: right;">
    <a href="{get_sort_link('players')}" target="_self" style="color: inherit; text-decoration: none;">PERIOD<br>PLAYERS<span class="sort-indicator">{get_sort_indicator('players')}</span></a>
</th>
<th class="header-link" {get_header_style('matches')} style="text-align: right;">
    <a href="{get_sort_link('matches')}" target="_self" style="color: inherit; text-decoration: none;">PERIOD<br>MATCHES<span class="sort-indicator">{get_sort_indicator('matches')}</span></a>
</th>
</tr>
</thead>
<tbody id="meta-table-body">
    """
    )
    
    # Build rows
    # Logic for diffs similar to original
    
    # Identify Reference Cards for Diff (against the #1 archetype in the current sort)
    ref_cards = []
    if show_diffs and rows_data:
        top_row = rows_data[0]
        ref_cards = top_row["deck_info"].get("cards", [])
    
    def cards_to_bag(c_list):
        return Counter({(c.get("set"), c.get("number")): c.get("count", 1) for c in c_list})

    ref_bag = cards_to_bag(ref_cards) if ref_cards else Counter()

    for row in rows_data:
        # Build Link preserving existing params
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        if row.get("cid"):
            link_params["cluster_id"] = [row["cid"]]
            if "deck_sig" in link_params: del link_params["deck_sig"]
        else:
            link_params["deck_sig"] = [row["sig"]]
            if "cluster_id" in link_params: del link_params["cluster_id"]
        
        link_params["page"] = ["trends"]
        from urllib.parse import urlencode
        link = "?" + urlencode(link_params, doseq=True) if (row["sig"] or row.get("cid")) else "?"
        
        # Tooltip
        tooltip_html = ""
        current_cards = []
        if row["deck_info"]:
            raw_cards = row["deck_info"].get("cards", [])
            current_cards = _enrich_and_sort_cards(raw_cards) # Ensure sorted
            
            img_count, MAX = 0, 30
            for card in current_cards:
                if img_count >= MAX: break
                c_set, c_num = card.get("set", ""), card.get("number", "")
                if not c_set or not c_num: continue
                
                # Revert to standard construction as per user feedback
                try: p_num = f"{int(c_num):03d}"
                except: p_num = c_num
                
                img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                
                for _ in range(card.get("count", 1)):
                    if img_count >= MAX: break
                    tooltip_html += f'<img src="{img}" class="tooltip-card" title="{get_display_name(card)}" onerror="this.style.display=\'none\'">'
                    img_count += 1
            tooltip_html = f'<div class="tooltip-grid">{tooltip_html}</div>'
        else:
            primary = row["name"].lower().replace(" ", "-")
            tooltip_html = f'<img src="{IMAGE_BASE_URL}/{primary}.jpg" onerror="this.src=\'{IMAGE_BASE_URL}/{primary}-ex.jpg\'; this.onerror=null;" style="width:180px;border-radius:8px;"><br>{row["name"]}'
        
        diff_cols_html = ""
        if show_diffs:
            added_cell = "-"
            removed_cell = "-"
            if ref_cards:
                current_bag = cards_to_bag(current_cards)
                added_ctr = current_bag - ref_bag
                removed_ctr = ref_bag - current_bag
                
                # Render mini cards for diff
                # Need lookup for set/number to render image
                # We can build a mini lookup from current_cards + ref_cards
                lookup = {}
                for c in current_cards + ref_cards:
                    key = (c.get("set"), c.get("number"))
                    lookup[key] = (c.get("set"), c.get("number"), c.get("image"), c.get("name"))
                
                def render_mini(ctr):
                    h = ""
                    for key, count in sorted(ctr.items()):
                        if key in lookup:
                            c_set, c_num, _, name = lookup[key]
                            try: p_num = f"{int(c_num):03d}"
                            except: p_num = c_num
                            img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                            for _ in range(count):
                                h += f'<img src="{img}" class="diff-img" title="{name}" onerror="this.style.display=\'none\'">'
                    return h
                
                added_cell = render_mini(added_ctr)
                removed_cell = render_mini(removed_ctr)
            diff_cols_html = f"<td>{removed_cell}</td><td>{added_cell}</td>"

        wr_color = '#1ed760' if row['wr'] > 50 else '#ff4b4b'

        # Key Cards for the last column
        cards_html = ""
        if current_cards:
            key_cards_to_show = 5 # Limit to 5 key cards
            for i, card in enumerate(current_cards):
                if i >= key_cards_to_show: break
                c_set, c_num = card.get("set", ""), card.get("number", "")
                
                if c_set and c_num:
                    try: p_num = f"{int(c_num):03d}"
                    except: p_num = c_num
                    img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                    cards_html += f'<img src="{img}" class="diff-img" title="{get_display_name(card)}" onerror="this.style.display=\'none\'">'

        row_html = (
            f'<tr class="meta-row-link" data-name="{row["name"].lower()}" '
            f'data-share="{row["share"]}" data-period-share="{row["period_share"]}" data-wr="{row["wr"]}" data-matches="{row["matches"]}" data-players="{row["players"]}" '
            f'onclick="if(!event.target.closest(\'a\')) {{ window.location.href=\'{link}\'; }}">'
            f'<td><div class="tooltip"><a href="{link}" target="_self" class="archetype-name">{row["full_name"]}</a>'
            f'<div class="tooltiptext">{tooltip_html}</div></div></td>'
            f'{diff_cols_html}'
            f'<td style="text-align: right; color: #1ed760; font-weight: bold;">{row["share"]:.1f}%</td>'
            f'<td style="text-align: right; opacity: 0.8;">{row["period_share"]:.1f}%</td>'
            f'<td style="text-align: right; color: {wr_color};">{row["wr"]:.1f}%</td>'
            f'<td style="text-align: right; color: #888;">{int(row["players"])}</td>'
            f'<td style="text-align: right; color: #888;">{int(row["matches"])}</td>'
            '</tr>\n'
        )
        html += textwrap.dedent(row_html)
        
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


def _render_deck_detail_view(sig, selected_period):
    if st.button("← Back to Trends"):
        if "deck_sig" in st.query_params:
            del st.query_params["deck_sig"]
        st.query_params["page"] = "trends"
        st.rerun()

    deck = get_deck_details(sig, start_date=selected_period["start"], end_date=selected_period["end"])
    if not deck:
        st.warning("Deck detail not found.")
        return
        
    # cards are already enriched in data.py

    st.title(deck.get("name", "Unknown Archetype"))
    st.caption(f"Signature: {sig}")

    stats = deck.get("stats", {})
    w, l, t = stats.get("wins", 0), stats.get("losses", 0), stats.get("ties", 0)
    total = w + l + t
    wr = (w / total * 100) if total > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{wr:.1f}%")
    c2.metric("Record", f"{w}W-{l}L-{t}T")
    c3.metric("Matches", total)
    c4.metric("Players", stats.get("players", 0))

    st.subheader("Card List")
    cards = deck.get("cards", [])
    render_card_grid(cards)

    st.subheader("Match History")
    render_match_history_table(deck.get("appearances", []))

def render_match_history_table(appearances):
    from src.data import get_match_history, get_deck_details_by_signature
    matches = get_match_history(appearances)
    if not matches:
        st.info("No detailed match records found.")
        return

    # Pre-fetch details for all opponents to build tooltips/checks
    opp_sigs = list(set([m["opponent_sig"] for m in matches if m.get("opponent_sig")]))
    opp_details = get_deck_details_by_signature(opp_sigs)
    # Cards are already enriched in data.py

    def format_player_link(row, role):
        t_id, name = row.get("t_id"), row.get(role)
        if not name: return "Unknown"
        p_id = name.lower().replace(" ", "-") # Basic guess
        if t_id:
            link = f"https://play.limitlesstcg.com/tournament/{t_id}/player/{p_id}"
            return f"<a href='{link}' target='_blank' class='archetype-name'>{name}</a>"
        return name

    def format_opponent_deck_cell(row):
        sig, deck_name = row["opponent_sig"], row["opponent_deck"]
        if not sig: return deck_name

        # Build Link preserving existing params
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        link_params["deck_sig"] = [sig]
        link_params["page"] = ["trends"]
        from urllib.parse import urlencode
        link = "?" + urlencode(link_params, doseq=True)
        name_html = f"<a href='{link}' target='_parent' class='archetype-name'>{deck_name}</a>"

        # Build Tooltip
        tooltip_html = ""
        direct_cards = row.get("opponent_cards", [])
        if not direct_cards and sig in opp_details:
            direct_cards = opp_details[sig].get("cards", [])
        
        if direct_cards:
            sorted_cards = _enrich_and_sort_cards(direct_cards)
            img_count, MAX = 0, 20
            for card in sorted_cards:
                if img_count >= MAX: break
                c_set, c_num = card.get("set", ""), card.get("number", "")
                try: p_num = f"{int(c_num):03d}"
                except: p_num = c_num
                img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                for _ in range(card.get("count", 1)):
                    if img_count >= MAX: break
                    tooltip_html += f'<img src="{img}" class="tooltip-card" title="{get_display_name(card)}">'
                    img_count += 1
            tooltip_html = f'<div class="tooltip-grid">{tooltip_html}</div>'
        else:
            tooltip_html = "No deck details available."

        return f'<div class="tooltip">{name_html}<div class="tooltiptext">{tooltip_html}</div></div>'

    # Python-side sorting for Match History
    m_sort = st.query_params.get("m_sort", "date")
    m_order = st.query_params.get("m_order", "desc")
    
    matches_to_sort = list(matches)
    sort_key_map = {
        "date": lambda x: x.get("date", ""),
        "tournament": lambda x: x.get("tournament", "").lower(),
        "round": lambda x: x.get("round", ""),
        "player": lambda x: x.get("player", "").lower(),
        "opponent": lambda x: x.get("opponent", "").lower(),
        "deck": lambda x: x.get("opponent_deck", "").lower(),
        "result": lambda x: x.get("result", "").lower()
    }
    if m_sort in sort_key_map:
        matches_to_sort.sort(key=sort_key_map[m_sort], reverse=(m_order == "desc"))

    def get_m_sort_link(col_name):
        new_order = "desc"
        if m_sort == col_name:
            new_order = "asc" if m_order == "desc" else "desc"
        params = {k: st.query_params.get_all(k) for k in st.query_params}
        params["m_sort"] = [col_name]
        params["m_order"] = [new_order]
        from urllib.parse import urlencode
        return "?" + urlencode(params, doseq=True)

    def get_m_sort_indicator(col_name):
        if m_sort == col_name: return " ▲" if m_order == "asc" else " ▼"
        return " ▴▾"

    def get_m_header_style(col_name):
        if m_sort == col_name: return 'style="color: #1ed760;"'
        return ''

    html = textwrap.dedent(f"""
        <table class="meta-table">
        <thead>
        <tr class="meta-header-row">
            <th {get_m_header_style('date')}><a href="{get_m_sort_link('date')}" target="_self" style="color: inherit; text-decoration: none;">Date{get_m_sort_indicator('date')}</a></th>
            <th {get_m_header_style('tournament')}><a href="{get_m_sort_link('tournament')}" target="_self" style="color: inherit; text-decoration: none;">Tournament{get_m_sort_indicator('tournament')}</a></th>
            <th {get_m_header_style('round')}><a href="{get_m_sort_link('round')}" target="_self" style="color: inherit; text-decoration: none;">Round{get_m_sort_indicator('round')}</a></th>
            <th {get_m_header_style('player')}><a href="{get_m_sort_link('player')}" target="_self" style="color: inherit; text-decoration: none;">Player{get_m_sort_indicator('player')}</a></th>
            <th {get_m_header_style('opponent')}><a href="{get_m_sort_link('opponent')}" target="_self" style="color: inherit; text-decoration: none;">Opponent{get_m_sort_indicator('opponent')}</a></th>
            <th {get_m_header_style('deck')}><a href="{get_m_sort_link('deck')}" target="_self" style="color: inherit; text-decoration: none;">Opponent Deck{get_m_sort_indicator('deck')}</a></th>
            <th {get_m_header_style('result')}><a href="{get_m_sort_link('result')}" target="_self" style="color: inherit; text-decoration: none;">Result{get_m_sort_indicator('result')}</a></th>
        </tr>
        </thead>
        <tbody>
    """)

    for m in matches_to_sort:
        p_link = format_player_link(m, "player")
        o_link = format_player_link(m, "opponent")
        d_cell = format_opponent_deck_cell(m)
        res = m.get("result", "T")
        res_color = "#1ed760" if res == "W" else "#ff4b4b" if res == "L" else "#888"
        html += textwrap.dedent(f"""
            <tr class="meta-row-link">
                <td>{m.get('date', '')}</td>
                <td style="font-size: 0.9em; opacity: 0.8;">{m.get('tournament', '')}</td>
                <td>{m.get('round', '')}</td>
                <td>{p_link}</td>
                <td>{o_link}</td>
                <td>{d_cell}</td>
                <td style="color: {res_color}; font-weight: bold;">{res}</td>
            </tr>
        """)
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

def _render_cluster_detail_view(cluster_id, selected_period):
    if st.button("← Back to Trends"):
        if "cluster_id" in st.query_params:
            del st.query_params["cluster_id"]
        st.query_params["page"] = "trends"
        st.rerun()

    cluster = get_cluster_details(cluster_id, start_date=selected_period["start"], end_date=selected_period["end"])
    if not cluster:
        st.warning("Cluster detail not found.")
        return

    st.title(f"Cluster: {cluster['name']}")
    st.caption(f"Cluster ID: {cluster_id}")

    stats = cluster["stats"]
    w, l, t = stats["wins"], stats["losses"], stats["ties"]
    total = w + l + t
    wr = (w / total * 100) if total > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aggregated Win Rate", f"{wr:.1f}%")
    c2.metric("Aggregated Record", f"{w}W-{l}L-{t}T")
    c3.metric("Total Matches", total)
    c4.metric("Total Players", stats["players"])

    # Representative Deck
    st.subheader("Representative Deck (Most Common)")
    rep_sig = cluster["representative_sig"]
    rep_deck = get_deck_details(rep_sig)
    
    if rep_deck and "cards" in rep_deck:
        render_card_grid(rep_deck["cards"])

    st.subheader("Variants in Cluster")
    variants = cluster["signatures"]
    
    # Identify Reference Cards for Diff (Cluster Representative)
    rep_deck = get_deck_details(cluster["representative_sig"])
    ref_cards = rep_deck.get("cards", []) if rep_deck else []
    
    def cards_to_bag(c_list):
        return Counter({(c.get("set"), c.get("number")): c.get("count", 1) for c in c_list})
    
    ref_bag = cards_to_bag(ref_cards)

    v_rows = []
    for sig, info in variants.items():
        v_stats = info.get("stats", {})
        vw, vl, vt = v_stats.get("wins", 0), v_stats.get("losses", 0), v_stats.get("ties", 0)
        v_total = vw + vl + vt
        v_wr = (vw / v_total * 100) if v_total > 0 else 0
        
        v_rows.append({
            "sig": sig,
            "name": info.get("name", "Unknown"),
            "wr": v_wr,
            "matches": v_total,
            "players": v_stats.get("players", 0),
            "cards": info.get("cards", [])
        })
    
    # Sorting logic for variants
    v_sort = st.query_params.get("v_sort", "players")
    v_order = st.query_params.get("v_order", "desc")
    
    v_sort_key_map = {
        "name": lambda x: x["name"].lower(),
        "wr": lambda x: x["wr"],
        "matches": lambda x: x["matches"],
        "players": lambda x: x["players"]
    }
    
    if v_sort in v_sort_key_map:
        v_rows.sort(key=v_sort_key_map[v_sort], reverse=(v_order == "desc"))

    def get_v_sort_link(col_name):
        new_order = "desc"
        if v_sort == col_name:
            new_order = "asc" if v_order == "desc" else "desc"
        params = {k: st.query_params.get_all(k) for k in st.query_params}
        params["v_sort"] = [col_name]
        params["v_order"] = [new_order]
        from urllib.parse import urlencode
        return "?" + urlencode(params, doseq=True)

    def get_v_sort_indicator(col_name):
        if v_sort == col_name: return " ▲" if v_order == "asc" else " ▼"
        return " ▴▾"

    def get_v_header_style(col_name):
        if v_sort == col_name: return 'style="color: #1ed760;"'
        return ''

    html = textwrap.dedent(f"""
        <table class="meta-table">
        <thead>
        <tr class="meta-header-row">
            <th {get_v_header_style('name')}><a href="{get_v_sort_link('name')}" target="_self" style="color: inherit; text-decoration: none;">VARIANT{get_v_sort_indicator('name')}</a></th>
            <th class="header-link">REMOVED</th>
            <th class="header-link">ADDED</th>
            <th {get_v_header_style('wr')} style="text-align: right;"><a href="{get_v_sort_link('wr')}" target="_self" style="color: inherit; text-decoration: none;">WIN RATE{get_v_sort_indicator('wr')}</a></th>
            <th {get_v_header_style('players')} style="text-align: right;"><a href="{get_v_sort_link('players')}" target="_self" style="color: inherit; text-decoration: none;">PLAYERS{get_v_sort_indicator('players')}</a></th>
            <th {get_v_header_style('matches')} style="text-align: right;"><a href="{get_v_sort_link('matches')}" target="_self" style="color: inherit; text-decoration: none;">MATCHES{get_v_sort_indicator('matches')}</a></th>
        </tr>
        </thead>
        <tbody>
    """)

    for row in v_rows:
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        link_params["deck_sig"] = [row["sig"]]
        if "cluster_id" in link_params: del link_params["cluster_id"]
        link_params["page"] = ["trends"]
        from urllib.parse import urlencode
        link = "?" + urlencode(link_params, doseq=True)
        
        # Diff Calculation
        current_bag = cards_to_bag(row["cards"])
        added_ctr = current_bag - ref_bag
        removed_ctr = ref_bag - current_bag
        
        lookup = {}
        for c in row["cards"] + ref_cards:
            key = (c.get("set"), c.get("number"))
            lookup[key] = (c.get("set"), c.get("number"), c.get("name"))
            
        def render_mini(ctr):
            h = ""
            for key, count in sorted(ctr.items()):
                if key in lookup:
                    c_set, c_num, name = lookup[key]
                    if not c_set or not c_num: continue
                    try: p_num = f"{int(c_num):03d}"
                    except: p_num = c_num
                    img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                    for _ in range(count):
                        h += f'<img src="{img}" class="diff-img" title="{name}" onerror="this.style.display=\'none\'">'
            return h
            
        added_html = render_mini(added_ctr)
        removed_html = render_mini(removed_ctr)
        
        wr_color = '#1ed760' if row['wr'] > 50 else '#ff4b4b'
        
        # Tooltip for Variant (Deck List)
        tooltip_html = ""
        enriched_cards = _enrich_and_sort_cards(row["cards"])
        img_count, MAX = 0, 30
        for card in enriched_cards:
            if img_count >= MAX: break
            c_set, c_num = card.get("set", ""), card.get("number", "")
            if not c_set or not c_num: continue
            try: p_num = f"{int(c_num):03d}"
            except: p_num = c_num
            img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
            for _ in range(card.get("count", 1)):
                if img_count >= MAX: break
                tooltip_html += f'<img src="{img}" class="tooltip-card" title="{get_display_name(card)}" onerror="this.style.display=\'none\'">'
                img_count += 1
        tooltip_html = f'<div class="tooltip-grid">{tooltip_html}</div>'

        html += textwrap.dedent(f"""
            <tr class="meta-row-link" onclick="if(!event.target.closest('a')) {{ window.location.href='{link}'; }}">
                <td><div class="tooltip"><a href="{link}" target="_self" class="archetype-name">{row['name']} ({row['sig']})</a><div class="tooltiptext">{tooltip_html}</div></div></td>
                <td>{removed_html}</td>
                <td>{added_html}</td>
                <td style="text-align: right; color: {wr_color}; font-weight: bold;">{row['wr']:.1f}%</td>
                <td style="text-align: right; color: #888;">{int(row['players'])}</td>
                <td style="text-align: right; color: #888;">{int(row['matches'])}</td>
            </tr>
        """)

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

    st.subheader("Aggregated Match History")
    render_match_history_table(cluster["appearances"])
