import streamlit as st
import pandas as pd
import re
import html
import textwrap
from collections import Counter
from urllib.parse import urlencode
from src.data import get_comparison_stats, get_deck_details_by_signature
from src.ui import (
    _get_set_periods, format_card_name, render_filtered_cards, 
    sort_card_ids, render_card_grid, get_display_name
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

    # 5. Matchup Matrix
    _render_matchup_matrix(sigs, selected_period, deck_details, sig_to_color)

    # Show Deck Details (Cards)
    st.divider()
    st.subheader("Deck Details")
    for i, sig in enumerate(sigs):
        color = sig_to_color.get(sig, "#ccc")
        
        # Construct Link
        link_params = {"period": [selected_period["code"]]}
        if sig.startswith("Cluster "):
            try:
                cid = sig.split("Cluster ")[1].split(")")[0]
                link_params["page"] = ["trends"]
                link_params["cluster_id"] = [cid]
            except: pass
        elif sig in id_to_cluster:
            link_params["page"] = ["trends"]
            link_params["cluster_id"] = [sig]
        else:
            link_params["page"] = ["details"]
            link_params["deck_sig"] = [sig]
        
        from urllib.parse import urlencode
        query_str = "?" + urlencode(link_params, doseq=True)
        
        st.markdown(
            f'<div style="display: flex; align-items: center; margin-bottom: 5px;">'
            f'<div style="width: 12px; height: 12px; background-color: {color}; border-radius: 50%; margin-right: 8px;"></div>'
            f'<a href="{query_str}" target="_blank" style="text-decoration: none; color: inherit;">'
            f'<span style="font-weight: bold; font-size: 1.1em; border-bottom: 1px dashed #666;">{get_label(sig)}</span>'
            f'</a>'
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
                        h += f'<img src="{img}" style="height: 24px; width: auto; border-radius: 2px; margin: 1px;" title="{html.escape(name)}" onerror="this.style.display=\'none\'">'
            return h or "-"

        # Link to trends
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        if "sig" in link_params: del link_params["sig"]
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

    table_html = textwrap.dedent(f"""
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
        
        table_html += textwrap.dedent(f"""
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

    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)

def _render_matchup_matrix(sigs, period, deck_details, sig_to_color):
    st.divider()
    st.subheader("Matchup Matrix (vs Top Meta Decks)")
    caption_text = "Matches between your selected decks and the top 8 distinct deck clusters in the metagame for this period."
    if st.session_state.get("show_japanese_toggle", False):
        caption_text += " (セル内: 勝ち越し確率、勝率、試合数)"
    else:
        caption_text += " (Cell: Win Probability, Win Rate, Matches)"
    st.caption(caption_text)

    # Move Heatmap Basis selector here
    col_m1, col_m2 = st.columns([1, 2])
    with col_m1:
        metric_options = ["Win Probability (Bayesian)", "Win Rate", "Matches"]
        if st.session_state.get("show_japanese_toggle", False):
            metric_options = ["勝ち越し確率 (ベイズ)", "勝率", "試合数"]
        
        heatmap_metric = st.selectbox(
            "Heatmap Basis", 
            options=["Prob", "WR", "Matches"],
            format_func=lambda x: metric_options[["Prob", "WR", "Matches"].index(x)],
            key="matchup_heatmap_metric"
        )

    with st.spinner("Calculating matchup statistics..."):
        from src.data import (
            get_clustered_daily_share_data, get_period_statistics, 
            get_cluster_mapping, get_match_history
        )
        
        # 1. Get Top 8 Clusters (Opponents)
        share_df = get_clustered_daily_share_data(
            start_date=period["start"], 
            end_date=period["end"]
        )
        period_stats = get_period_statistics(
            share_df, 
            start_date=period["start"], 
            end_date=period["end"], 
            clustered=True
        )
        
        # Sort by share and pick top 8
        sorted_clusters = sorted(
            period_stats.items(), 
            key=lambda x: x[1].get("avg_share", 0), 
            reverse=True
        )[:8]
        
        opponents = []
        sig_to_cluster_id = {}
        cluster_id_to_name = {}
        
        sig_to_cluster, id_to_cluster = get_cluster_mapping()
        
        for label, info in sorted_clusters:
            # label is "Cluster {id} ({name})"
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
                    cluster_id_to_name[cid] = name
                    # Map all signatures in this cluster to this cluster ID
                    for s in id_to_cluster[cid].get("signatures", []):
                        sig_to_cluster_id[s] = cid
            except: continue

        if not opponents:
            st.warning("Could not identify top metagame decks for this period.")
            return
            
        # Fetch cards for opponents' representative decks for tooltips
        opp_rep_sigs = [opp["rep_sig"] for opp in opponents]
        opp_rep_details = get_deck_details_by_signature(opp_rep_sigs)
        for opp in opponents:
            opp_info = opp_rep_details.get(opp["rep_sig"]) or {}
            opp["cards"] = opp_info.get("cards", [])

        # 2. Get Match History for selected decks
        # We need appearances for each selected deck to get their matches
        matrix_data = {} # (selected_sig, opponent_cluster_id) -> {w, l, t}
        
        from src.data import _get_all_signatures
        all_sigs_data = _get_all_signatures()
        
        all_appearances_to_lookup = []
        app_to_sig_map = {} # (t_id, player_id, date) -> list of comparison_sigs
        
        for sig in sigs:
            # Resolve sig to target signatures (if it's a cluster)
            target_sigs = []
            if sig.startswith("Cluster "):
                try:
                    cid = sig.split("Cluster ")[1].split(")")[0]
                    if cid in id_to_cluster:
                        target_sigs = id_to_cluster[cid]["signatures"]
                except: pass
            elif sig in id_to_cluster:
                target_sigs = id_to_cluster[sig]["signatures"]
            else:
                target_sigs = [sig]
            
            # Get appearances for these signatures in the period
            for t_sig in target_sigs:
                if t_sig in all_sigs_data:
                    apps = all_sigs_data[t_sig].get("appearances", [])
                    # Filter by period
                    for a in apps:
                        d = a["date"]
                        if (not period["start"] or d >= period["start"]) and (not period["end"] or d <= period["end"]):
                            app_key = (a["t_id"], a["player_id"], d)
                            if app_key not in app_to_sig_map:
                                app_to_sig_map[app_key] = []
                                all_appearances_to_lookup.append(a)
                            app_to_sig_map[app_key].append(sig)
            
        if all_appearances_to_lookup:
            all_matches = get_match_history(all_appearances_to_lookup)
            
            for m in all_matches:
                opp_sig = m.get("opponent_sig")
                if opp_sig in sig_to_cluster_id:
                    cid = sig_to_cluster_id[opp_sig]
                    res = m.get("result")
                    
                    # Map this match back to all comparison sigs that share this appearance
                    app_key = (m["t_id"], m["player"], m["date"])
                    for comp_sig in app_to_sig_map.get(app_key, []):
                        key = (comp_sig, cid)
                        if key not in matrix_data:
                            matrix_data[key] = {"w": 0, "l": 0, "t": 0}
                        
                        if res == "Win": matrix_data[key]["w"] += 1
                        elif res == "Loss": matrix_data[key]["l"] += 1
                        elif res == "Tie": matrix_data[key]["t"] += 1

    # 3. Render Matrix
    from src.data import load_translations
    show_ja = st.session_state.get("show_japanese_toggle", False)
    trans = load_translations() if show_ja else {}

    def get_display_name(ident):
        details = deck_details.get(ident, {}) or {}
        return details.get("name", ident)

    table_html = textwrap.dedent(f"""
        <style>
        .matchup-matrix th, .matchup-matrix td {{ padding: 8px 4px; text-align: center; vertical-align: middle; min-width: 65px; }}
        .matchup-header-row th {{ background-color: #1a1c24; color: #888; text-transform: uppercase; font-size: 9px; letter-spacing: 0.05em; position: relative; }}
        .matchup-side-col {{ background-color: #1a1c24; text-align: left !important; font-weight: 500; min-width: 140px !important; }}
        .matchup-cell {{ border-radius: 3px; position: relative; }}
        .cell-main {{ font-size: 1.1em; font-weight: bold; display: block; }}
        .cell-sub {{ font-size: 0.85em; opacity: 0.8; display: block; }}
        .cell-matches {{ font-size: 0.75em; opacity: 0.5; display: block; }}
        
        /* Tooltip styles */
        .header-tooltip {{ position: relative; display: inline-block; width: 100%; height: 100%; }}
        .tooltiptext {{
            visibility: hidden; width: 340px; background-color: #1e1e1e; color: #fff;
            text-align: center; border-radius: 8px; padding: 10px; position: absolute;
            z-index: 1000; top: 110%; left: 50%; transform: translateX(-50%);
            opacity: 0; transition: opacity 0.3s, transform 0.3s; 
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
            pointer-events: none;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .matchup-header-row th:hover .tooltiptext {{ visibility: visible; opacity: 1; transform: translateX(-50%) translateY(5px); }}
        .tooltip-grid {{ display: grid; grid-template-columns: repeat(10, 1fr); gap: 2px; justify-items: center; margin-top: 5px; }}
        .tooltip-card-img {{ width: 30px; height: auto; border-radius: 2px; }}
        </style>
        <div style="overflow-x: auto;">
        <table class="matchup-matrix">
            <thead>
                <tr class="matchup-header-row">
                    <th style="background: none;"></th>
    """).strip()
    
    for opp in opponents:
        name = opp["name"]
        if show_ja: name = trans.get(name, name)
        
        # Link to cluster detail
        link_params = {
            "page": ["trends"],
            "cluster_id": [opp["id"]],
            "period": [period["code"]]
        }
        query_str = "?" + urlencode(link_params, doseq=True)
        
        query_str = "?" + urlencode(link_params, doseq=True)
        
        # Build cards grid for tooltip
        card_html = '<div class="tooltip-grid">'
        if opp.get("cards"):
            from src.ui import _enrich_and_sort_cards
            sorted_cards = _enrich_and_sort_cards(opp["cards"])
            for c in sorted_cards:
                c_set = c.get("set", "")
                c_num = c.get("number", "")
                try: p_num = f"{int(c_num):03d}"
                except: p_num = c_num
                img = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                count = c.get("count", 1)
                for _ in range(count):
                    safe_c_name = html.escape(c.get("name") or c.get("card_name") or "Unknown")
                    card_html += f'<img src="{img}" class="tooltip-card-img" title="{safe_c_name}">'
        card_html += '</div>'
        
        table_html += textwrap.dedent(f"""
            <th>
                <div class="header-tooltip">
                    <a href="{query_str}" target="_self" style="color: #1ed760; text-decoration: none;">{name}</a>
                    <div class="tooltiptext">
                        <div style="font-weight: bold; margin-bottom: 5px;">{name}</div>
                        {card_html}
                    </div>
                </div>
            </th>
        """).strip()
    table_html += "</tr></thead><tbody>"

    for sig in sigs:
        row_name = get_display_name(sig)
        if show_ja: row_name = trans.get(row_name, row_name)
        color = sig_to_color.get(sig, "#ccc")
        
        # Row header with dot and signature
        table_html += textwrap.dedent(f"""
            <tr>
                <td class="matchup-side-col">
                    <div style="display: flex; align-items: center; margin-bottom: 2px;">
                        <span style="width: 8px; height: 8px; border-radius: 50%; background-color: {color}; margin-right: 6px; display: inline-block;"></span>
                        <span style="font-weight: 600;">{row_name}</span>
                    </div>
                    <div style="font-size: 0.8em; opacity: 0.5; margin-left: 14px;">{sig}</div>
                </td>
        """).strip()
        
        for opp in opponents:
            cid = opp["id"]
            stats = matrix_data.get((sig, cid), {"w": 0, "l": 0, "t": 0})
            w, l, t = stats["w"], stats["l"], stats["t"]
            total = w + l + t
            
            wr = (w / total * 100) if total > 0 else 0
            from src.utils import calculate_confidence_interval, calculate_bayesian_win_probability
            lower, _ = calculate_confidence_interval(w, total)
            prob = calculate_bayesian_win_probability(w, total)
            
            # Heatmap Color
            bg_color = "rgba(40, 42, 54, 0.8)" # Default gray-ish
            if total > 0:
                if heatmap_metric == "Prob":
                    if prob > 50:
                        alpha = min(0.8, 0.2 + (prob - 50) / 50)
                        bg_color = f"rgba(84, 112, 198, {alpha})" # Blue
                    elif prob < 50:
                        alpha = min(0.8, 0.2 + (50 - prob) / 50)
                        bg_color = f"rgba(238, 102, 102, {alpha})" # Red
                    else:
                        bg_color = "rgba(255, 255, 255, 0.1)" # White/Neutral
                elif heatmap_metric == "WR":
                    if wr > 50:
                        alpha = min(0.8, 0.2 + (wr - 50) / 50)
                        bg_color = f"rgba(84, 112, 198, {alpha})" # Blue
                    elif wr < 50:
                        alpha = min(0.8, 0.2 + (50 - wr) / 50)
                        bg_color = f"rgba(238, 102, 102, {alpha})" # Red
                    else:
                        bg_color = "rgba(255, 255, 255, 0.1)" # White/Neutral
                elif heatmap_metric == "Matches":
                    # For matches, we use a simple linear scale relative to a reasonable "high" value (e.g., 50)
                    alpha = min(0.8, 0.1 + (total / 50) * 0.7)
                    bg_color = f"rgba(145, 204, 117, {alpha})" # Green-ish for volume
            
            table_html += f'<td class="matchup-cell" style="background-color: {bg_color};">'
            if total > 0:
                # Order: Win Prob, WR, Matches
                table_html += f'<span class="cell-main" title="Win Probability">{prob:.1f}%</span>'
                table_html += f'<span class="cell-sub" title="Win Rate">{wr:.1f}%</span>'
                table_html += f'<span class="cell-matches">{total} matches</span>'
            else:
                table_html += '<span style="opacity: 0.2;">-</span>'
            table_html += "</td>"
            
        table_html += "</tr>"
        
    table_html += "</tbody></table></div>"
    st.markdown(table_html, unsafe_allow_html=True)
