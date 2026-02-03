
import json
import os
from datetime import datetime, timedelta
import logging
import re
import textwrap
import pandas as pd
import streamlit as st
from collections import Counter

from src.data import get_daily_share_data, get_deck_details, get_all_card_names, get_match_history, enrich_card_data
from src.visualizations import create_echarts_stacked_area, display_chart
from src.config import IMAGE_BASE_URL
from src.utils import format_deck_name

logger = logging.getLogger(__name__)

@st.cache_data(ttl=3600)
def _get_card_type_map():
    # In this implementation, card types are already enriched in data.py
    # But for sorting, we need the order.
    pass

def _enrich_and_sort_cards(cards):
    """Sort cards by Pokemon > Item > Tool > Stadium > Supporter."""
    # First, ensure types are correct/enriched using our new logic
    cards = enrich_card_data(cards)
    
    type_order = {
        "Pokemon": 0,
        "Goods": 1,
        "Item": 2,
        "Stadium": 3,
        "Support": 4,
        "Unknown": 5,
    }

    # Sort: type_order, then name
    cards.sort(
        key=lambda x: (type_order.get(x.get("type", "Unknown"), 5), x.get("name", ""))
    )
    return cards

@st.cache_data(ttl=600)
def _get_cached_trend_data(selected_cards, exclude_cards, window, start_date=None, end_date=None, standard_only=False):
    # Call the data layer
    return get_daily_share_data(
        card_filters=selected_cards, 
        exclude_cards=exclude_cards, 
        window=window,
        start_date=start_date,
        end_date=end_date,
        standard_only=standard_only
    )

def _get_set_periods():
    sets_path = os.path.join("data", "cards", "sets.json")
    if not os.path.exists(sets_path):
        return []
    try:
        with open(sets_path, "r") as f:
            data = json.load(f)
        
        all_sets = []
        for series in data.values():
            for s in series:
                if "PROMO" not in s.get("code", ""):
                    all_sets.append(s)
        
        all_sets.sort(key=lambda x: x.get("releaseDate", "9999-99-99"), reverse=True)
        
        periods = [{"label": "All", "start": None, "end": None}]
        for i in range(len(all_sets)):
            s = all_sets[i]
            start = s.get("releaseDate")
            name = s.get("name", {}).get("en", s.get("code"))
            
            # End date for the newest set is None (Now)
            # End date for other sets is day before the one that was released AFTER it (which is the one before it in this descending list)
            end = None
            if i > 0:
                # This set ends the day before the set released after it (which is all_sets[i-1])
                pass 
                
        # Actually it is easier to calculate end dates FIRST then reverse.
        # Let's redo the logic slightly for clarity.
        all_sets.sort(key=lambda x: x.get("releaseDate", "9999-99-99"))
        
        processed_periods = []
        for i in range(len(all_sets)):
            s = all_sets[i]
            start = s.get("releaseDate")
            name = s.get("name", {}).get("en", s.get("code"))
            
            end = None
            if i < len(all_sets) - 1:
                end_dt = datetime.strptime(all_sets[i+1]["releaseDate"], "%Y-%m-%d") - timedelta(days=1)
                end = end_dt.strftime("%Y-%m-%d")
            
            label = f"{name} ({start} ~ {end if end else 'Now'})"
            processed_periods.append({"label": label, "start": start, "end": end, "name": name, "release": start})
        
        # Newest first
        processed_periods.sort(key=lambda x: x["release"], reverse=True)
        
        return [{"label": "All", "start": None, "end": None}] + processed_periods
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
        all_cards = get_all_card_names()
        periods = _get_set_periods()
        
        # Read from query params
        q_params = st.query_params
        default_cards = q_params.get_all("cards")
        default_exclude = q_params.get_all("exclude")
        default_period_label = q_params.get("period", "")
        try:
            default_window = int(q_params.get("window", 7))
        except:
            default_window = 7

        with col1:
            selected_cards = st.multiselect("Filter by Cards (AND)", options=all_cards, default=[c for c in default_cards if c in all_cards])
            exclude_cards = st.multiselect("Exclude Cards (NOT)", options=all_cards, default=[c for c in default_exclude if c in all_cards])

        with col2:
            period_options = [p["label"] for p in periods]
            # Default to the latest set (index 1) if available, otherwise "All" (index 0)
            
            # Find index of default period label
            try:
                period_idx = period_options.index(default_period_label)
            except ValueError:
                period_idx = 1 if len(period_options) > 1 else 0

            selected_period_label = st.selectbox("Aggregation Period", options=period_options, index=period_idx)
            selected_period = next(p for p in periods if p["label"] == selected_period_label)
            
            standard_only = selected_period["label"] != "All"

        with col3:
            window = st.slider(
                "Moving Average Window (Days)", min_value=1, max_value=14, value=default_window
            )

        # Update query params on change
        # Note: Streamlit's st.query_params handles multiple values for same key automatically with get_all/set_all
        # but for simple assignment, it replaces.
        st.query_params["cards"] = selected_cards
        st.query_params["exclude"] = exclude_cards
        st.query_params["period"] = selected_period_label
        st.query_params["window"] = window

    # Fetch Data
    with st.spinner("Aggregating daily share data..."):
        try:
            df = _get_cached_trend_data(
                selected_cards, 
                exclude_cards, 
                window,
                start_date=selected_period["start"],
                end_date=selected_period["end"],
                standard_only=standard_only
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
                    standard_only=standard_only
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
    """
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

    # Check for Drill-Down
    query_params = st.query_params
    selected_sig = query_params.get("deck_sig", None)
    if selected_sig:
        _render_deck_detail_view(selected_sig)
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

    # Fetch signatures and details early for both chart tooltips and table
    sig_map = {}
    for col in df.columns:
        match = re.search(r"\(([\da-f]{8})\)$", col)
        if match:
            sig_map[col] = match.group(1)

    # We need deck details for chart tooltips (and table)
    from src.data import get_deck_details_by_signature
    valid_sigs = [s for s in sig_map.values() if s]
    details_map = get_deck_details_by_signature(valid_sigs)
    
    # Enrich details map with types for tooltips
    for sig in details_map:
        if "cards" in details_map[sig]:
            details_map[sig]["cards"] = enrich_card_data(details_map[sig]["cards"])

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
            # clicked_series will be the series name (e.g. "Pikachu & Zekrom (abcd1234)")
            # We need to extract the signature
            match = re.search(r"\(([\da-f]{8})\)$", clicked_series)
            if match:
                sig = match.group(1)
                st.query_params["deck_sig"] = sig
                st.query_params["page"] = "trends"
                st.rerun()

    # Table
    st.subheader("Current Metagame Share")
    st.caption("Click headers to sort instantly. Click rows for details.")

    # Prepare Data for Table
    show_diffs = (selected_cards or exclude_cards) and global_df is not None and not global_df.empty
    
    # We already have sig_map and details_map from above
    
    rows_data = []
    
    for name_with_sig, share in latest_shares.items():
        if share <= 0:
            continue
        
        sig = sig_map.get(name_with_sig)
        name_clean = name_with_sig.split("(")[0].strip()
        
        deck_info = details_map.get(sig, {})
        stats = deck_info.get("stats", {})
        
        # Calculate WR
        w, l, t = stats.get("wins", 0), stats.get("losses", 0), stats.get("ties", 0)
        mtch = w + l + t
        wr = (w / mtch * 100) if mtch > 0 else 0.0
        
        rows_data.append({
            "sig": sig,
            "full_name": name_with_sig,
            "name": name_clean,
            "share": share,
            "wr": wr,
            "matches": mtch,
            "deck_info": deck_info
        })

    # Python-side sorting
    sort_col = st.query_params.get("sort", "share")
    sort_order = st.query_params.get("order", "desc")
    
    # Sort mapping
    sort_key_map = {
        "name": lambda x: x["name"].lower(),
        "share": lambda x: x["share"],
        "wr": lambda x: x["wr"],
        "matches": lambda x: x["matches"]
    }
    
    if sort_col in sort_key_map:
        rows_data.sort(key=sort_key_map[sort_col], reverse=(sort_order == "desc"))

    def get_sort_link(col_name):
        new_order = "desc"
        if sort_col == col_name:
            new_order = "asc" if sort_order == "desc" else "desc"
        
        # Build query string from current params but override sort/order
        # Use get_all for all keys to preserve multi-value params like 'cards'
        params = {k: st.query_params.get_all(k) for k in st.query_params}
        params["sort"] = [col_name]
        params["order"] = [new_order]
        
        from urllib.parse import urlencode
        return "?" + urlencode(params, doseq=True)

    def get_sort_indicator(col_name):
        if sort_col == col_name:
            return " ▲" if sort_order == "asc" else " ▼"
        return " ▴▾"

    def get_header_style(col_name):
        if sort_col == col_name:
            return 'style="color: #1ed760;"'
        return ''

    diff_headers = ""
    if show_diffs:
        diff_headers = '<th class="header-link">Removed</th><th class="header-link">Added</th>'

    html = textwrap.dedent(
        f"""
<table class="meta-table">
<thead>
<tr class="meta-header-row">
<th class="header-link" {get_header_style('name')}>
    <a href="{get_sort_link('name')}" target="_self" style="color: inherit; text-decoration: none;">Archetype<span class="sort-indicator">{get_sort_indicator('name')}</span></a>
</th>
{diff_headers}
<th class="header-link" {get_header_style('share')} style="text-align: right;">
    <a href="{get_sort_link('share')}" target="_self" style="color: inherit; text-decoration: none;">Share <span class="sort-indicator">{get_sort_indicator('share')}</span></a>
</th>
<th class="header-link" {get_header_style('wr')} style="text-align: right;">
    <a href="{get_sort_link('wr')}" target="_self" style="color: inherit; text-decoration: none;">WinRate <span class="sort-indicator">{get_sort_indicator('wr')}</span></a>
</th>
<th class="header-link" {get_header_style('matches')} style="text-align: right;">
    <a href="{get_sort_link('matches')}" target="_self" style="color: inherit; text-decoration: none;">Matches <span class="sort-indicator">{get_sort_indicator('matches')}</span></a>
</th>
</tr>
</thead>
<tbody id="meta-table-body">
    """
    )
    
    # Build rows
    # Logic for diffs similar to original
    
    # Identify Top Sig for Diff
    top_sig = None
    if show_diffs:
         for name, share in latest_shares.items():
            if share > 0:
                s = sig_map.get(name)
                if s: 
                    top_sig = s
                    break
    
    ref_cards = []
    if top_sig:
        d = get_deck_details(top_sig)
        if d: ref_cards = d.get("cards", [])

    def cards_to_bag(c_list):
        return Counter({c["name"]: c.get("count", 1) for c in c_list})

    ref_bag = cards_to_bag(ref_cards) if ref_cards else Counter()

    for row in rows_data:
        # Build Link preserving existing params
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        link_params["deck_sig"] = [row["sig"]]
        link_params["page"] = ["trends"]
        from urllib.parse import urlencode
        link = "?" + urlencode(link_params, doseq=True) if row["sig"] else "?"
        
        # Tooltip
        tooltip_html = ""
        current_cards = []
        if row["deck_info"]:
            raw_cards = row["deck_info"].get("cards", [])
            current_cards = _enrich_and_sort_cards(raw_cards) # Ensure sorted
            
            img_count, MAX = 0, 20
            for card in current_cards:
                if img_count >= MAX: break
                c_set, c_num = card.get("set", ""), card.get("number", "")
                try: p_num = f"{int(c_num):03d}"
                except: p_num = c_num
                img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                for _ in range(card.get("count", 1)):
                    if img_count >= MAX: break
                    tooltip_html += f'<img src="{img}" class="tooltip-card">'
                    img_count += 1
            tooltip_html = f'<div class="tooltip-grid">{tooltip_html}</div>'
        else:
            primary = row["name"].lower().replace(" ", "-")
            tooltip_html = f'<img src="{IMAGE_BASE_URL}/{primary}.jpg" onerror="this.src=\'{IMAGE_BASE_URL}/{primary}-ex.jpg\'; this.onerror=null;" style="width:180px;border-radius:8px;"><br>{row["name"]}'
        
        # Diff columns
        diff_cols_html = ""
        if show_diffs:
            added_cell = "-"
            removed_cell = "-"
            if top_sig and row["sig"]:
                current_bag = cards_to_bag(current_cards)
                added_ctr = current_bag - ref_bag
                removed_ctr = ref_bag - current_bag
                
                # Render mini cards for diff
                # Need lookup for set/number to render image
                # We can build a mini lookup from current_cards + ref_cards
                lookup = {}
                for c in current_cards + ref_cards:
                    lookup[c["name"]] = (c.get("set"), c.get("number"))
                
                def render_mini(ctr):
                    h = ""
                    for name, count in sorted(ctr.items()):
                        if name in lookup:
                            c_set, c_num = lookup[name]
                            try: p_num = f"{int(c_num):03d}"
                            except: p_num = c_num
                            img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                            for _ in range(count):
                                h += f'<img src="{img}" class="diff-img" title="{name}">'
                    return h
                
                added_cell = render_mini(added_ctr)
                removed_cell = render_mini(removed_ctr)
            diff_cols_html = f"<td>{removed_cell}</td><td>{added_cell}</td>"

        color_wr = '#1ed760' if row['wr'] > 50 else '#ff4b4b'
        row_html = (
            f'<tr class="meta-row-link" data-name="{row["name"].lower()}" '
            f'data-share="{row["share"]}" data-wr="{row["wr"]}" data-matches="{row["matches"]}" '
            f'onclick="if(!event.target.closest(\'a\')) {{ window.location.href=\'{link}\'; }}">'
            f'<td><div class="tooltip"><a href="{link}" target="_self" class="archetype-name">{row["full_name"]}</a>'
            f'<div class="tooltiptext">{tooltip_html}</div></div></td>'
            f'{diff_cols_html}'
            f'<td style="text-align: right; color: #1ed760; font-weight: bold;">{row["share"]:.1f}%</td>'
            f'<td style="text-align: right; color: {color_wr};">{row["wr"]:.1f}%</td>'
            f'<td style="text-align: right; color: #888;">{int(row["matches"])}</td>'
            '</tr>\n'
        )
        html += textwrap.dedent(row_html)
        
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


def _render_deck_detail_view(sig):
    if st.button("← Back to Trends"):
        if "deck_sig" in st.query_params:
            del st.query_params["deck_sig"]
        st.query_params["page"] = "trends"
        st.rerun()

    deck = get_deck_details(sig)
    if not deck:
        st.warning("Deck detail not found.")
        return
        
    if "cards" in deck:
        deck["cards"] = enrich_card_data(deck["cards"])

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
    if cards:
        enriched_cards = _enrich_and_sort_cards(cards)
        
        all_copies = []
        for c in enriched_cards:
            count = c.get("count", 1)
            for _ in range(count):
                all_copies.append(c)

        if all_copies:
            cols_per_row = 10
            for i in range(0, len(all_copies), cols_per_row):
                row_cards = all_copies[i : i + cols_per_row]
                cols = st.columns(cols_per_row)
                for j, c in enumerate(row_cards):
                    c_set = c.get("set", "")
                    c_num = c.get("number", "")
                    try: p_num = f"{int(c_num):03d}"
                    except: p_num = c_num
                    img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                    with cols[j]:
                        st.image(img, caption=c.get("name"), width="stretch")

    st.subheader("Match History")
    from src.data import get_match_history, get_deck_details_by_signature

    apps = deck.get("appearances", [])
    matches = get_match_history(apps)
    if matches:
        mdf = pd.DataFrame(matches)

        # Pre-fetch details for all opponents to build tooltips/checks
        opp_sigs = list(set([m["opponent_sig"] for m in matches if m.get("opponent_sig")]))
        opp_details = get_deck_details_by_signature(opp_sigs)
        for s in opp_details:
             if "cards" in opp_details[s]:
                 opp_details[s]["cards"] = enrich_card_data(opp_details[s]["cards"])

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
                        tooltip_html += f'<img src="{img}" class="tooltip-card">'
                        img_count += 1
                tooltip_html = f'<div class="tooltip-grid">{tooltip_html}</div>'
            else:
                tooltip_html = "No deck details available."

            return f'<div class="tooltip">{name_html}<div class="tooltiptext">{tooltip_html}</div></div>'

        # Python-side sorting for Match History
        m_sort = st.query_params.get("m_sort", "date")
        m_order = st.query_params.get("m_order", "desc")
        
        # Prepare display columns and handle sorting
        # We need a copy of the list of dicts for sorting
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
            if m_sort == col_name:
                return " ▲" if m_order == "asc" else " ▼"
            return " ▴▾"

        def get_m_header_style(col_name):
            if m_sort == col_name:
                return 'style="color: #1ed760;"'
            return ''

        # Build Table HTML
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
    else:
        st.info("No detailed match records found.")
