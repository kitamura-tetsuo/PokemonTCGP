import streamlit as st
import pandas as pd
import re
import textwrap
from collections import Counter
from urllib.parse import urlencode
from src.data import get_comparison_stats, get_deck_details_by_signature
from src.ui import (
    _get_set_periods, format_card_name, render_filtered_cards, 
    sort_card_ids, render_card_grid
)
from src.visualizations import create_echarts_line_comparison, display_chart
from src.utils import calculate_confidence_interval
from src.config import IMAGE_BASE_URL

def render_comparison_page():
    st.header("Deck Comparison")
    st.markdown("Compare multiple decks by their signatures. View share trends, win rates, and Wilson confidence lower bounds.")

    # URL Params
    qp = st.query_params
    default_sigs = qp.get_all("sigs")
    default_period_code = qp.get("period", "All")
    try:
        default_window = int(qp.get("window", 7))
    except:
        default_window = 7

    # Controls
    with st.expander("Controls", expanded=True):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            sig_input = st.text_area(
                "Deck Signatures (comma or newline separated)", 
                value=", ".join(default_sigs) if default_sigs else "",
                help="Example: 8be51084, a3b2c1d0"
            )
            # Parse signatures
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
            
            selected_period_label = st.selectbox("Period", options=period_options, index=period_idx)
            selected_period = next(p for p in periods if p["label"] == selected_period_label)
            
            window = st.slider("Moving Average Window", 1, 14, default_window)

    # Sync URL
    st.query_params["sigs"] = sigs
    st.query_params["period"] = selected_period["code"]
    st.query_params["window"] = window

    if not sigs:
        st.info("Enter deck signatures to begin comparison.")
        return

    # Fetch Data
    with st.spinner("Calculating comparison statistics..."):
        stats_dict = get_comparison_stats(
            sigs, 
            window=window, 
            start_date=selected_period["start"], 
            end_date=selected_period["end"]
        )
        
        # Resolve names and details for labels and layouts (supporting clusters)
        from src.data import get_cluster_mapping
        _, id_to_cluster = get_cluster_mapping()
        
        resolved_sigs_for_details = []
        ident_to_rep_sig = {}
        for ident in sigs:
            if ident.startswith("Cluster "):
                try:
                    cid = ident.split("Cluster ")[1].split(")")[0]
                    if cid in id_to_cluster:
                        rep_sig = id_to_cluster[cid]["representative_sig"]
                        resolved_sigs_for_details.append(rep_sig)
                        ident_to_rep_sig[ident] = rep_sig
                except: pass
            elif ident in id_to_cluster:
                 rep_sig = id_to_cluster[ident]["representative_sig"]
                 resolved_sigs_for_details.append(rep_sig)
                 ident_to_rep_sig[ident] = rep_sig
            else:
                 resolved_sigs_for_details.append(ident)
                 ident_to_rep_sig[ident] = ident
                 
        raw_details = get_deck_details_by_signature(resolved_sigs_for_details)
        deck_details = {ident: raw_details.get(ident_to_rep_sig.get(ident)) for ident in sigs}

    if not stats_dict:
        st.warning("No data found for the provided signatures.")
        return

    # Prepare labels and colors mapping
    ECHARTS_COLORS = [
        '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', 
        '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc'
    ]
    sig_to_color = {sig: ECHARTS_COLORS[i % len(ECHARTS_COLORS)] for i, sig in enumerate(sigs)}

    def get_label(ident):
        if ident.startswith("Cluster "): 
            return ident
        details = deck_details.get(ident, {}) or {}
        name = details.get("name", "Unknown")
        return f"{name} ({ident})"

    # 1. Share Chart
    st.subheader("Daily Metagame Share (%)")
    share_df = pd.DataFrame({get_label(s): df["share"] for s, df in stats_dict.items()})
    share_opt = create_echarts_line_comparison(share_df, title="", y_axis_label="Share (%)")
    
    # Apply consistent colors
    if "series" in share_opt:
        for series in share_opt["series"]:
            name = series.get("name", "")
            match = re.search(r"\(([\w ]+)\)$", name)
            if match and match.group(1) in sig_to_color:
                series["itemStyle"] = {"color": sig_to_color[match.group(1)]}

    display_chart(share_opt, height="400px")

    # 2. Win Rate Chart
    st.subheader("Daily Win Rate (%)")
    wr_df = pd.DataFrame({get_label(s): df["wr"] for s, df in stats_dict.items()})
    wr_opt = create_echarts_line_comparison(wr_df, title="", y_axis_label="Win Rate (%)")
    
    # Apply consistent colors and add match counts to tooltips
    if "series" in wr_opt:
        for series in wr_opt["series"]:
            name = series.get("name", "")
            match = re.search(r"\(([\w ]+)\)$", name)
            if match and match.group(1) in sig_to_color:
                sig = match.group(1)
                series["itemStyle"] = {"color": sig_to_color[sig]}
                
                # Add Matches to tooltip
                df = stats_dict[sig]
                new_data = []
                for d_idx, val in enumerate(series["data"]):
                    date = wr_df.index[d_idx]
                    m = df.loc[date, "matches_moving"]
                    wr_val = f"{val:.2f}%" if pd.notna(val) else "-"
                    tooltip_str = (
                        f"<div style='font-family: sans-serif; padding: 5px;'>"
                        f"<div style='font-weight: bold;'>{name}</div>"
                        f"<div>{date}</div>"
                        f"<div>Win Rate (avg): {wr_val}</div>"
                        f"<div>Matches (Window): {int(m)}</div>"
                        f"</div>"
                    )
                    new_data.append({
                        "value": val,
                        "tooltip": {"formatter": tooltip_str}
                    })
                series["data"] = new_data

    display_chart(wr_opt, height="400px")

    # 3. Wilson Lower Bounds Chart
    st.subheader("Wilson Score Interval (Lower Bound)")
    st.caption("Cumulative vs. Moving Lower Bound. Cumulative (solid) shows overall reliability, Moving (dashed) shows recent performance.")
    
    wilson_data = {}
    for s, df in stats_dict.items():
        label = get_label(s)
        wilson_data[f"{label} (Moving)"] = df["wilson_moving"]
        wilson_data[f"{label} (Cumulative)"] = df["wilson_cumulative"]
    
    wilson_df = pd.DataFrame(wilson_data)
    wilson_opt = create_echarts_line_comparison(wilson_df, title="", y_axis_label="Lower Bound (%)")
    
    # Inject line styles, consistent colors, and match counts into Wilson chart
    if "series" in wilson_opt:
        for series in wilson_opt["series"]:
            name = series.get("name", "")
            # Extract sig or cluster name from label
            match = re.search(r"\(([\w ]+)\)", name) # Matches (8be51084) or (Cluster 1)
            if match and match.group(1) in sig_to_color:
                sig = match.group(1)
                series["itemStyle"] = {"color": sig_to_color[sig]}
                
                df = stats_dict[sig]
                new_data = []
                is_cum = "(Cumulative)" in name
                
                for d_idx, val in enumerate(series["data"]):
                    date = wilson_df.index[d_idx]
                    m = df.loc[date, "matches_cumulative" if is_cum else "matches_moving"]
                    val_fmt = f"{val:.2f}%" if pd.notna(val) else "-"
                    m_label = "Cumulative" if is_cum else "Window"
                    
                    tooltip_str = (
                        f"<div style='font-family: sans-serif; padding: 5px;'>"
                        f"<div style='font-weight: bold;'>{name}</div>"
                        f"<div>{date}</div>"
                        f"<div>Lower Bound: {val_fmt}</div>"
                        f"<div>Matches ({m_label}): {int(m)}</div>"
                        f"</div>"
                    )
                    new_data.append({
                        "value": val,
                        "tooltip": {"formatter": tooltip_str}
                    })
                series["data"] = new_data
                
            if "(Cumulative)" in name:
                series["lineStyle"] = {"type": "solid", "width": 3}
                series["opacity"] = 1.0
            elif "(Moving)" in name:
                series["lineStyle"] = {"type": "dashed", "width": 1}
                series["opacity"] = 0.8
                
    display_chart(wilson_opt, height="500px")

    # 4. Comparison Table
    _render_comparison_table(sigs, stats_dict, deck_details, sig_to_color)

    # Show Deck Details (Cards)
    st.divider()
    st.subheader("Deck Details")
    for i, sig in enumerate(sigs):
        color = sig_to_color.get(sig, "#ccc")
        st.markdown(
            f'<div style="display: flex; align-items: center; margin-bottom: 5px;">'
            f'<div style="width: 12px; height: 12px; background-color: {color}; border-radius: 50%; margin-right: 8px;"></div>'
            f'<span style="font-weight: bold; font-size: 1.1em;">{get_label(sig)}</span>'
            f'</div>',
            unsafe_allow_html=True
        )
        details = deck_details.get(sig)
        if details and "cards" in details:
            render_card_grid(details["cards"])
        else:
            st.write("No card data available.")
        if i < len(sigs) - 1:
            st.markdown("<br>", unsafe_allow_html=True)

def _render_comparison_table(sigs, stats_dict, deck_details, sig_to_color):
    st.divider()
    st.subheader("Comparison Statistics")
    
    show_ja = st.session_state.get("show_japanese_toggle", False)
    
    # Headers
    col_name = "デッキ名" if show_ja else "Deck"
    col_rem = "除外" if show_ja else "Rem."
    col_add = "追加" if show_ja else "Add"
    col_share_l = "最新シェア" if show_ja else "Latest Share"
    col_share_t = "通期シェア" if show_ja else "Avg Share"
    col_wr_l = "最新勝率" if show_ja else "Latest WR"
    col_wr_t = "通期勝率" if show_ja else "Avg WR"
    col_lower = "下 (95%)" if show_ja else "Lower"
    col_upper = "上 (95%)" if show_ja else "Upper"
    col_players = "使用者数" if show_ja else "Players"
    col_matches = "試合数" if show_ja else "Matches"

    # Baseline: First deck
    def cards_to_bag(c_list):
        if not c_list: return Counter()
        return Counter({(c.get("set"), c.get("number")): c.get("count", 1) for c in c_list})
    
    first_sig = sigs[0]
    first_details = deck_details.get(first_sig) or {}
    first_bag = cards_to_bag(first_details.get("cards", []))
    
    table_data = []
    for sig in sigs:
        df = stats_dict.get(sig)
        if df is None: continue
        
        details = deck_details.get(sig) or {}
        
        # Share & WR
        latest_share = df["share"].iloc[-1]
        avg_share = df["share"].mean()
        
        latest_wr = df["wr"].iloc[-1]
        
        total_matches = df["matches_daily"].sum()
        # Note: stats_dict doesn't have total wins directly per day, but we can infer it 
        # Actually, get_comparison_stats returns 'wr' daily. 
        # To get the true cumulative WR, we need cumulative wins.
        # stats_dict[sig] has 'matches_cumulative' and 'wilson_cumulative'.
        # wilson_cumulative is lower bound. 
        # Let's recreate total wins from cumulative stats at the last date.
        last_row = df.iloc[-1]
        cum_matches = last_row["matches_cumulative"]
        
        total_wins = last_row["wins_cumulative"]
        
        cum_wr = (total_wins / cum_matches * 100) if cum_matches > 0 else 0
        lower_ci, upper_ci = calculate_confidence_interval(total_wins, int(cum_matches))
        
        # Diffs
        curr_bag = cards_to_bag(details.get("cards", []))
        added_ctr = curr_bag - first_bag
        removed_ctr = first_bag - curr_bag
        
        # Render Mini Cards (reuse lookup logic)
        lookup = {}
        all_cards = (first_details.get("cards", []) or []) + (details.get("cards", []) or [])
        for c in all_cards:
            key = (c.get("set"), c.get("number"))
            lookup[key] = (c.get("set"), c.get("number"), c.get("name"))
            
        def render_mini(ctr):
            h = ""
            for key, count in sorted(ctr.items()):
                if key in lookup:
                    c_set, c_num, name = lookup[key]
                    try: p_num = f"{int(c_num):03d}"
                    except: p_num = c_num
                    img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                    for _ in range(count):
                        h += f'<img src="{img}" style="height: 24px; width: auto; border-radius: 2px; margin: 1px;" title="{name}" onerror="this.style.display=\'none\'">'
            return h or "-"

        # Link to trends
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        link_params["deck_sig"] = [sig]
        link_params["page"] = ["trends"]
        # Clear comparison params to make it a clean jump
        if "sigs" in link_params: del link_params["sigs"]
        query_str = "?" + urlencode(link_params, doseq=True)

        table_data.append({
            "sig": sig,
            "name": details.get("name", "Unknown"),
            "color": sig_to_color.get(sig, "#ccc"),
            "added": render_mini(added_ctr),
            "removed": render_mini(removed_ctr),
            "share_latest": latest_share,
            "share_avg": avg_share,
            "wr_latest": latest_wr,
            "wr_avg": cum_wr,
            "lower": lower_ci,
            "upper": upper_ci,
            "players": details.get("stats", {}).get("players", 0), # This might need to be period-specific
            "matches": int(cum_matches),
            "link": query_str
        })

    # Sorting
    sort_key = st.query_params.get("c_sort", "share_avg")
    sort_order = st.query_params.get("c_order", "desc")
    
    if sort_key in table_data[0]:
        table_data.sort(key=lambda x: x[sort_key] if pd.notna(x[sort_key]) else -1, reverse=(sort_order == "desc"))

    def get_sort_link(key):
        new_order = "desc"
        if sort_key == key:
            new_order = "asc" if sort_order == "desc" else "desc"
        params = {k: st.query_params.get_all(k) for k in st.query_params}
        params["c_sort"] = [key]
        params["c_order"] = [new_order]
        return "?" + urlencode(params, doseq=True)

    def get_indicator(key):
        if sort_key == key: return " ▲" if sort_order == "asc" else " ▼"
        return " ▴▾"

    html = textwrap.dedent(f"""
        <style>
        .comp-table {{ font-family: sans-serif; font-size: 13px; width: 100%; color: #eee; border-collapse: collapse; margin-top: 10px; }}
        .comp-header-row {{ font-weight: bold; border-bottom: 2px solid rgba(255,255,255,0.2); background-color: #1a1c24; }}
        .comp-table th {{ padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left; color: #888; text-transform: uppercase; letter-spacing: 0.05em; font-size: 10px; }}
        .comp-row-link {{ display: table-row; cursor: pointer; transition: background 0.15s; text-decoration: none; color: inherit; height: 40px; }}
        .comp-row-link:hover {{ background-color: rgba(255,255,255,0.05); }}
        .deck-color-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }}
        </style>
        <table class="comp-table">
            <thead>
            <tr class="comp-header-row">
                <th>{col_name}</th>
                <th>{col_rem}</th>
                <th>{col_add}</th>
                <th style="text-align: right;"><a href="{get_sort_link('share_latest')}" target="_self" style="color: inherit; text-decoration: none;">{col_share_l}{get_indicator('share_latest')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('share_avg')}" target="_self" style="color: inherit; text-decoration: none;">{col_share_t}{get_indicator('share_avg')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('wr_latest')}" target="_self" style="color: inherit; text-decoration: none;">{col_wr_l}{get_indicator('wr_latest')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('wr_avg')}" target="_self" style="color: inherit; text-decoration: none;">{col_wr_t}{get_indicator('wr_avg')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('lower')}" target="_self" style="color: inherit; text-decoration: none;">{col_lower}{get_indicator('lower')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('upper')}" target="_self" style="color: inherit; text-decoration: none;">{col_upper}{get_indicator('upper')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('players')}" target="_self" style="color: inherit; text-decoration: none;">{col_players}{get_indicator('players')}</a></th>
                <th style="text-align: right;"><a href="{get_sort_link('matches')}" target="_self" style="color: inherit; text-decoration: none;">{col_matches}{get_indicator('matches')}</a></th>
            </tr>
            </thead>
            <tbody>
    """).strip()

    for row in table_data:
        wr_color = '#1ed760' if row['wr_avg'] > 50 else '#ff4b4b'
        l_wr_color = '#1ed760' if row['wr_latest'] > 50 else '#ff4b4b'
        
        wr_latest_str = f"{row['wr_latest']:.1f}%" if pd.notna(row['wr_latest']) else "-"
        
        html += textwrap.dedent(f"""
            <tr class="comp-row-link" onclick="window.location.href='{row['link']}'">
                <td>
                    <div style="display: flex; align-items: center;">
                        <span class="deck-color-dot" style="background-color: {row['color']};"></span>
                        <span style="font-weight: 500;">{row['name']}</span>
                    </div>
                    <div style="font-size: 0.8em; opacity: 0.5; margin-left: 14px;">{row['sig']}</div>
                </td>
                <td>{row['removed']}</td>
                <td>{row['added']}</td>
                <td style="text-align: right;">{row['share_latest']:.2f}%</td>
                <td style="text-align: right; font-weight: 600;">{row['share_avg']:.2f}%</td>
                <td style="text-align: right; color: {l_wr_color};">{wr_latest_str}</td>
                <td style="text-align: right; color: {wr_color}; font-weight: 600;">{row['wr_avg']:.1f}%</td>
                <td style="text-align: right; opacity: 0.7;">{row['lower']:.1f}%</td>
                <td style="text-align: right; opacity: 0.7;">{row['upper']:.1f}%</td>
                <td style="text-align: right;">{row['players']}</td>
                <td style="text-align: right;">{row['matches']}</td>
            </tr>
        """).strip()

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)
