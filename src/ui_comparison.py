import streamlit as st
import pandas as pd
import re
from src.data import get_comparison_stats, get_deck_details_by_signature
from src.ui import (
    _get_set_periods, format_card_name, render_filtered_cards, 
    sort_card_ids, render_card_grid
)
from src.visualizations import create_echarts_line_comparison, display_chart

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
