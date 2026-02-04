import streamlit as st
import pandas as pd
import itertools
import textwrap
from collections import Counter
from urllib.parse import urlencode
from src.data import get_multi_group_trend_data, get_all_card_ids, get_group_details
from src.ui import (
    _get_set_periods, format_card_name, render_filtered_cards, sort_card_ids,
    render_card_grid, render_match_history_table, get_display_name,
    _enrich_and_sort_cards # Need this for diffs
)
from src.config import IMAGE_BASE_URL
from src.visualizations import display_chart, create_echarts_line_comparison

def render_combinations_page():
    st.header("Card Combination Analysis")
    st.markdown("Analyze how the presence or absence of specific cards impacts deck performance.")

    # Shared CSS for both main page and detail views
    st.markdown(textwrap.dedent("""
        <style>
        .meta-table { font-family: sans-serif; font-size: 14px; width: 100%; color: #eee; border-collapse: collapse; margin-top: 10px; }
        .meta-header-row { font-weight: bold; border-bottom: 2px solid rgba(255,255,255,0.2); background-color: #1a1c24; }
        .meta-table th { padding: 12px 15px; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left; color: #888; text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px; }
        .meta-row-link { display: table-row; cursor: pointer; transition: background 0.15s; text-decoration: none; color: inherit; }
        .meta-row-link:hover { background-color: rgba(255,255,255,0.05); }
        .archetype-name { font-weight: 600; color: #1ed760; text-decoration: none; }
        .archetype-name:hover { text-decoration: underline; }
        .card-grid {
            display: grid;
            grid-template-columns: repeat(25, 1fr);
            gap: 2px;
            margin-top: 5px;
        }
        .card-item {
            width: 100%;
            position: relative;
        }
        .card-img {
            width: 100%;
            height: auto;
            border-radius: 2px;
            display: block;
            transition: transform 0.2s;
        }
        .card-img:hover {
            transform: scale(1.1);
            z-index: 10;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
        }
        .diff-img {
            height: 30px;
            width: auto;
            border-radius: 2px;
            margin: 1px;
        }
        .tooltip-card {
            height: 30px;
            width: auto;
            border-radius: 2px;
            margin: 1px;
        }
        </style>
    """), unsafe_allow_html=True)

    all_card_ids = get_all_card_ids()

    # --- Query Param Defaults ---
    qp = st.query_params
    q_v_inc = qp.get_all("v_inc")
    q_v_exc = qp.get_all("v_exc")
    
    q_period = qp.get("period")
    q_window = int(qp.get("window", 7))
    q_include = qp.get_all("include")
    q_exclude = qp.get_all("exclude")
    q_vars = qp.get_all("vars")

    # Validate Card IDs
    q_include = [c for c in q_include if c in all_card_ids]
    q_exclude = [c for c in q_exclude if c in all_card_ids and c not in q_include]
    q_vars = [c for c in q_vars if c in all_card_ids and c not in q_include and c not in q_exclude]

    # --- Controls ---
    with st.container():
        col1, col2 = st.columns(2)
        periods = _get_set_periods()
        with col1:
             period_options = [p["label"] for p in periods]
             # Determine index
             default_idx = 1 if len(periods) > 1 else 0
             if q_period:
                 # Try finding by code
                 for i, p in enumerate(periods):
                     if p["code"] == q_period:
                         default_idx = i
                         break
                 else:
                     # Fallback to label match
                     if q_period in period_options:
                         default_idx = period_options.index(q_period)
             
             selected_period_label = st.selectbox("Aggregation Period", options=period_options, index=default_idx)
             selected_period = next(p for p in periods if p["label"] == selected_period_label)
             standard_only = selected_period["code"] != "All"
        with col2:
             window = st.slider("Moving Average Window (Days)", min_value=1, max_value=14, value=q_window)

    st.divider()

    # --- Router for Detail View ---
    if q_v_inc or q_v_exc:
        _render_group_variants_view(q_v_inc, q_v_exc, selected_period)
        return

    # --- Global Filters ---
    st.subheader("1. Global Filters")
    st.caption("These conditions apply to ALL generated groups.")
    
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        global_include = st.multiselect("Always Include (AND)", options=all_card_ids, default=q_include, help="Decks must contain ALL of these cards.", format_func=format_card_name)
        global_include = sort_card_ids(global_include)
        render_filtered_cards(global_include)
    with col_g2:
        # Filter options to exclude already included cards
        exclude_options = [c for c in all_card_ids if c not in global_include]
        # Clean default exclude if it conflicts with current include (user interactions)
        curr_exclude_default = [c for c in q_exclude if c in exclude_options]
        
        global_exclude = st.multiselect("Always Exclude (NOT)", options=exclude_options, default=curr_exclude_default, help="Decks must NOT contain ANY of these cards.", format_func=format_card_name)
        global_exclude = sort_card_ids(global_exclude)
        render_filtered_cards(global_exclude)

    st.divider()

    # --- Variation Cards ---
    st.subheader("2. Comparison Variables")
    st.caption("Select cards to compare. All meaningful combinations (Presence/Absence) will be analyzed.")
    
    # Filter options
    var_options = [c for c in all_card_ids if c not in global_include and c not in global_exclude]
    curr_vars_default = [c for c in q_vars if c in var_options]

    var_cards = st.multiselect("Select Variables", options=var_options, default=curr_vars_default, format_func=format_card_name)
    var_cards = sort_card_ids(var_cards)
    render_filtered_cards(var_cards)

    # --- Sync to URL ---
    st.query_params["period"] = selected_period["code"]
    st.query_params["window"] = window
    st.query_params["include"] = global_include
    st.query_params["exclude"] = global_exclude
    st.query_params["vars"] = var_cards
    
    if len(var_cards) > 4:
        st.warning(f"You have selected {len(var_cards)} variables. This will generate {2**len(var_cards)} lines on the chart, which may be hard to read.")

    # --- Analysis (Auto-Run) ---
    if not var_cards and not global_include and not global_exclude:
        st.info("Select cards above to see analysis.")
        return

    with st.spinner(f"Analyzing {2**len(var_cards) if var_cards else 1} combinations..."):
        
        # Generate Groups
        groups = []
        
        if not var_cards:
            # Base case: Just Global Filters
            groups.append({
                "label": "Base Group",
                "include": global_include,
                "exclude": global_exclude
            })
        else:
            # Generate Power Set of inclusions/exclusions for var_cards
            patterns = list(itertools.product([True, False], repeat=len(var_cards)))
            
            for p in patterns:
                local_inc = []
                local_exc = []
                label_parts = []
                
                for i, is_included in enumerate(p):
                    card = var_cards[i]
                    if is_included:
                        local_inc.append(card)
                        label_parts.append(card)
                    else:
                        local_exc.append(card)
                        
                # Construct Label
                if not label_parts:
                    label = "None"
                    if len(var_cards) == 1:
                        label = f"No {format_card_name(var_cards[0])}"
                    else:
                        label = "Neither/None" 
                else:
                    present_cards = [format_card_name(var_cards[i]) for i, x in enumerate(p) if x]
                    if len(present_cards) == len(var_cards):
                        label = "All Variables (" + " + ".join(present_cards) + ")"
                    elif len(present_cards) == 0:
                        label = "None"
                    else:
                        label = " + ".join(present_cards)
                        
                # Merge with Global
                final_include = global_include + local_inc
                final_exclude = global_exclude + local_exc
                
                groups.append({
                    "label": label,
                    "include": final_include,
                    "exclude": final_exclude,
                    "sort_key": len(local_inc) 
                })
            
            # Sort groups
            groups.sort(key=lambda x: x["sort_key"], reverse=True)

        results = get_multi_group_trend_data(
            groups, 
            window=window, 
            start_date=selected_period["start"], 
            end_date=selected_period["end"],
            standard_only=standard_only
        )
        
        df_share = results["share"]
        df_wr = results["wr"]
        df_match = results["matches"]
        
        if df_share.empty:
            st.warning("No data found matching the criteria.")
        else:
            show_ja = st.session_state.get("show_japanese_toggle", False)
            # Share Chart
            st.subheader("Metagame Share")
            label_share = "シェア" if show_ja else "Share"
            label_wr = "勝率" if show_ja else "Win Rate"
            
            opt_share = create_echarts_line_comparison(
                df_share, 
                y_axis_label=f"{label_share} (%)",
                secondary_df=df_wr,
                secondary_label=label_wr
            )
            display_chart(opt_share)
            
            # Win Rate Chart
            st.subheader("Win Rate")
            opt_wr = create_echarts_line_comparison(
                df_wr, 
                y_axis_label=f"{label_wr} (%)",
                secondary_df=df_share,
                secondary_label=label_share
            )
            display_chart(opt_wr)
            
            # Summary Table
            st.subheader("Period Statistics")
            summary = []
            
            # Columns
            col_group = "グループ" if show_ja else "Group"
            col_share = "平均シェア" if show_ja else "Avg Share"
            col_wr = "平均勝率" if show_ja else "Avg Win Rate"
            col_matches = "試合数" if show_ja else "Matches"
            col_inc = "含むカード" if show_ja else "Includes"
            col_exc = "除外カード" if show_ja else "Excludes"

            for g in groups:
                lbl = g["label"]
                if lbl in df_share.columns:
                    avg_share = df_share[lbl].mean()
                    avg_wr = df_wr[lbl].mean()
                    total_matches = df_match[lbl].sum()
                    
                    summary.append({
                        col_group: lbl,
                        col_share: avg_share,
                        col_wr: avg_wr,
                        col_matches: int(total_matches),
                        col_inc: ", ".join(g["include"]) if len(g["include"]) <= 3 else f"{len(g['include'])} cards",
                        col_exc: ", ".join(g["exclude"]) if len(g["exclude"]) <= 3 else f"{len(g['exclude'])} cards"
                    })
            # Sorting Logic for Summary
            p_sort = st.query_params.get("p_sort", "share")
            p_order = st.query_params.get("p_order", "desc")

            sort_key_map = {
                "share": col_share,
                "wr": col_wr,
                "matches": col_matches
            }
            
            # Helper for sort links
            def get_p_sort_link(key):
                new_order = "desc"
                if p_sort == key:
                    new_order = "asc" if p_order == "desc" else "desc"
                
                params = {k: st.query_params.get_all(k) for k in st.query_params}
                params["p_sort"] = [key]
                params["p_order"] = [new_order]
                # Clean up v_inc/v_exc just in case, though usually not present here
                if "v_inc" in params: del params["v_inc"]
                if "v_exc" in params: del params["v_exc"]
                
                return "?" + urlencode(params, doseq=True)

            def get_p_sort_indicator(key):
                if p_sort == key: return " ▲" if p_order == "asc" else " ▼"
                return " ▴▾"

            def get_p_header_style(key):
                if p_sort == key: return 'style="color: #1ed760; text-align: right;"'
                return 'style="text-align: right;"'

            # Sort the summary list
            if p_sort in sort_key_map:
                sort_col = sort_key_map[p_sort]
                summary.sort(key=lambda x: x[sort_col], reverse=(p_order == "desc"))

            if summary:
                # Custom HTML Table for clickable rows
                st.write("") # Spacer
                
                params_base = {k: st.query_params.get_all(k) for k in st.query_params}
                if "v_inc" in params_base: del params_base["v_inc"]
                if "v_exc" in params_base: del params_base["v_exc"]
                if "p_sort" in params_base: del params_base["p_sort"]
                if "p_order" in params_base: del params_base["p_order"]

                # Link builders needs to preserve p_sort/p_order if we want them to persist when navigating back? 
                # Actually, navigating to detail and back usually resets unless we explicitly pass them.
                # For now, let's just make sure the table headers work.

                html = textwrap.dedent(f"""
                <table class="meta-table">
                    <thead>
                    <tr class="meta-header-row">
                        <th>{col_group}</th>
                        <th {get_p_header_style('share')}><a href="{get_p_sort_link('share')}" target="_self" style="color: inherit; text-decoration: none;">{col_share}{get_p_sort_indicator('share')}</a></th>
                        <th {get_p_header_style('wr')}><a href="{get_p_sort_link('wr')}" target="_self" style="color: inherit; text-decoration: none;">{col_wr}{get_p_sort_indicator('wr')}</a></th>
                        <th {get_p_header_style('matches')}><a href="{get_p_sort_link('matches')}" target="_self" style="color: inherit; text-decoration: none;">{col_matches}{get_p_sort_indicator('matches')}</a></th>
                        <th>{col_inc}</th>
                        <th>{col_exc}</th>
                    </tr>
                    </thead>
                    <tbody>
                """).strip()

                for i, row in enumerate(summary):
                    g = groups[i] if i < len(groups) else None
                    if not g: continue
                    
                    link_params = params_base.copy()
                    link_params["v_inc"] = g["include"]
                    link_params["v_exc"] = g["exclude"]
                    query_str = "?" + urlencode(link_params, doseq=True)
                    
                    wr_color = '#1ed760' if row[col_wr] > 50 else '#ff4b4b'
                    
                    html += textwrap.dedent(f"""
                    <tr class="meta-row-link" onclick="window.location.href='{query_str}'">
                        <td><a href="{query_str}" target="_self" class="archetype-name">{row[col_group]}</a></td>
                        <td style="text-align: right;">{row[col_share]:.2f}%</td>
                        <td style="text-align: right; color: {wr_color};">{row[col_wr]:.2f}%</td>
                        <td style="text-align: right;">{row[col_matches]}</td>
                        <td style="font-size: 0.85em; opacity: 0.7;">{row[col_inc]}</td>
                        <td style="font-size: 0.85em; opacity: 0.7;">{row[col_exc]}</td>
                    </tr>
                    """)
                
                html += "</tbody></table>"
                st.markdown(html, unsafe_allow_html=True)


def _render_group_variants_view(include_cards, exclude_cards, period):
    if st.button("← Back to Analysis"):
        if "v_inc" in st.query_params: del st.query_params["v_inc"]
        if "v_exc" in st.query_params: del st.query_params["v_exc"]
        st.rerun()

    with st.spinner("Loading group details..."):
        details = get_group_details(include_cards, exclude_cards, start_date=period["start"], end_date=period["end"])

    if not details:
        st.warning("No data found for this group in the selected period.")
        return

    st.header("Group Variant Details")
    
    # Breadcrumbs-like info
    inc_names = [format_card_name(c) for c in include_cards]
    exc_names = [format_card_name(c) for c in exclude_cards]
    
    st.markdown(f"**Includes:** {', '.join(inc_names) if inc_names else 'None'}")
    if exc_names:
        st.markdown(f"**Excludes:** {', '.join(exc_names)}")

    stats = details["stats"]
    w, l, t = stats["wins"], stats["losses"], stats["ties"]
    total = w + l + t
    wr = (w / total * 100) if total > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{wr:.1f}%")
    c2.metric("Record", f"{w}W-{l}L-{t}T")
    c3.metric("Total Matches", total)
    c4.metric("Total Players", stats["players"])

    st.divider()

    st.subheader("Representative Deck")
    render_card_grid(details["cards"])

    st.divider()

    st.subheader("Variants matching these cards")
    
    # Baseline for diffs: Representative Deck
    def cards_to_bag(c_list):
        return Counter({(c.get("set"), c.get("number")): c.get("count", 1) for c in c_list})
    
    ref_cards = details.get("cards", [])
    ref_bag = cards_to_bag(ref_cards)
    
    v_data = []
    for sig, info in details["signatures"].items():
        v_stats = info.get("stats", {})
        vw, vl, vt = v_stats.get("wins", 0), v_stats.get("losses", 0), v_stats.get("ties", 0)
        vt_total = vw + vl + vt
        v_wr = (vw / vt_total * 100) if vt_total > 0 else 0
        
        # Calculate Diffs
        curr_cards = info.get("cards", [])
        curr_bag = cards_to_bag(curr_cards)
        added_ctr = curr_bag - ref_bag
        removed_ctr = ref_bag - curr_bag
        
        # Render Mini Cards
        # Build lookup for images from both ref and curr
        lookup = {}
        for c in ref_cards + curr_cards:
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
                        h += f'<img src="{img}" class="diff-img" title="{name}" onerror="this.style.display=\'none\'">'
            return h or "-"

        added_html = render_mini(added_ctr)
        removed_html = render_mini(removed_ctr)
        
        # Link to deck detail view
        link_params = {k: st.query_params.get_all(k) for k in st.query_params}
        link_params["deck_sig"] = [sig]
        link_params["page"] = ["trends"]
        deck_link = "?" + urlencode(link_params, doseq=True)
        
        v_data.append({
            "Signature": sig,
            "Name": info.get("name", "Unknown"),
            "Win Rate": f"{v_wr:.1f}%",
            "wr_raw": v_wr,
            "Players": v_stats.get("players", 0),
            "Matches": vt_total,
            "added": added_html,
            "removed": removed_html,
            "link": deck_link
        })
    
    # Sorting Logic
    v_sort = st.query_params.get("v_sort", "players")
    v_order = st.query_params.get("v_order", "desc")
    
    sort_key_map = {
        "players": lambda x: x["Players"],
        "wr": lambda x: x["wr_raw"],
        "matches": lambda x: x["Matches"]
    }
    if v_sort in sort_key_map:
        v_data.sort(key=sort_key_map[v_sort], reverse=(v_order == "desc"))

    def get_v_sort_link(col_name):
        new_order = "desc"
        if v_sort == col_name:
            new_order = "asc" if v_order == "desc" else "desc"
        params = {k: st.query_params.get_all(k) for k in st.query_params}
        params["v_sort"] = [col_name]
        params["v_order"] = [new_order]
        return "?" + urlencode(params, doseq=True)

    def get_v_sort_indicator(col_name):
        if v_sort == col_name: return " ▲" if v_order == "asc" else " ▼"
        return " ▴▾"

    def get_v_header_style(col_name):
        if v_sort == col_name: return 'style="color: #1ed760;"'
        return ''

    # Display variants as custom HTML table for links
    
    show_ja = st.session_state.get("show_japanese_toggle", False)
    col_wr = "勝率" if show_ja else "Win Rate"
    col_players = "使用者数" if show_ja else "Players"
    col_matches = "試合数" if show_ja else "Matches"
    col_removed = "除外" if show_ja else "Removed"
    col_added = "追加" if show_ja else "Added"
    col_name = "デッキ名" if show_ja else "Name"
    
    v_html = textwrap.dedent(f"""
        <table class="meta-table">
        <thead>
        <tr class="meta-header-row">
            <th>Signature</th>
            <th>{col_name}</th>
            <th>{col_removed}</th>
            <th>{col_added}</th>
            <th style="text-align: right;" {get_v_header_style('wr')}><a href="{get_v_sort_link('wr')}" target="_self" style="color: inherit; text-decoration: none;">{col_wr}{get_v_sort_indicator('wr')}</a></th>
            <th style="text-align: right;" {get_v_header_style('players')}><a href="{get_v_sort_link('players')}" target="_self" style="color: inherit; text-decoration: none;">{col_players}{get_v_sort_indicator('players')}</a></th>
            <th style="text-align: right;" {get_v_header_style('matches')}><a href="{get_v_sort_link('matches')}" target="_self" style="color: inherit; text-decoration: none;">{col_matches}{get_v_sort_indicator('matches')}</a></th>
        </tr>
        </thead>
        <tbody>
    """).strip()
    for v in v_data:
        row_html = textwrap.dedent(f"""
            <tr class="meta-row-link" onclick="window.location.href='{v['link']}'">
                <td style="font-family: monospace; font-size: 0.9em;">{v['Signature']}</td>
                <td><a href="{v['link']}" target="_self" class="archetype-name">{v['Name']}</a></td>
                <td>{v['removed']}</td>
                <td>{v['added']}</td>
                <td style="text-align: right;">{v['Win Rate']}</td>
                <td style="text-align: right;">{v['Players']}</td>
                <td style="text-align: right;">{v['Matches']}</td>
            </tr>
        """).strip()
        v_html += row_html
    
    v_html += "</tbody></table>"
    st.markdown(v_html, unsafe_allow_html=True)

    st.subheader("Match History for Group")
    render_match_history_table(details["appearances"])
