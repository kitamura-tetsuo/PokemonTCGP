import re
import json
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from src.config import CHART_COLORS, PLOTLY_CONFIG, IMAGE_BASE_URL
from src.data import get_card_name
from streamlit_echarts import st_echarts, JsCode

def create_echarts_stacked_area(df, details_map=None, title="Metagame Share Over Time"):
    """
    Create a stacked area chart using ECharts.
    """
    if df.empty:
        return None

    # Sort columns: most popular on top
    latest_shares = df.iloc[-1].sort_values(ascending=False)
    sorted_cols = latest_shares.index.tolist()
    
    # Prepare data for ECharts
    dates = df.index.tolist()
    series = []
    
    # ECharts colors (default palette is good, but we can customize)
    colors = [
        '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', 
        '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc'
    ]
    
    # We need to build a map of archetype -> card HTML for the tooltip formatter
    tooltip_data = {}
    
    show_ja = st.session_state.get("show_japanese_toggle", False)

    for i, archetype in enumerate(reversed(sorted_cols)):
        values = df[archetype].tolist()
        # Round values for display
        values = [round(v, 1) for v in values]
        
        # Build tooltip content for this archetype (Static HTML Images)
        sig = ""
        match = re.search(r"\(([\da-f]{8})\)$", archetype)
        if match:
            sig = match.group(1)
            
        card_html = ""
        if details_map and archetype in details_map:
             deck = details_map[archetype]
        elif details_map and sig in details_map:
            deck = details_map[sig]
        else:
            deck = None

        if deck:
            cards = deck.get("cards", [])
            type_order = {"Pokemon": 0, "Goods": 1, "Item": 2, "Stadium": 3, "Support": 4}
            sorted_cards = sorted(cards, key=lambda x: (type_order.get(x.get("type", "Unknown"), 5), x.get("name", "")))
            
            imgs_html = ""
            count = 0
            MAX_IMGS = 20 # Limit to prevent payload issues
            for c in sorted_cards:
                if count >= MAX_IMGS: break
                c_set = c.get("set", "")
                c_num = c.get("number", "")
                try: p_num = f"{int(c_num):03d}"
                except: p_num = c_num
                
                img_url = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                
                c_name = c.get("name")
                if show_ja:
                    c_name = get_card_name(c_name, "ja")

                for _ in range(c.get("count", 1)):
                    if count >= MAX_IMGS: break
                    imgs_html += f"<img src='{img_url}' title='{c_name}' style='width: 30px; height: auto; margin: 1px; border-radius: 2px;'>"
                    count += 1
            
            if imgs_html:
                 card_html = f"<div style='margin-top: 5px; width: 170px; display: flex; flex-wrap: wrap; line-height: 0;'>{imgs_html}</div>"

        series.append({
            "name": archetype,
            "type": "line",
            "stack": "Total",
            "areaStyle": {},
            "emphasis": {"focus": "series"},
            "data": values,
            "smooth": True,
            "showSymbol": True,
            "symbol": "circle",
            "symbolSize": 8,
            "itemStyle": {"opacity": 0},
            "lineStyle": {"width": 0},
            "tooltip": {
                "formatter": f"<div style='font-family: sans-serif; padding: 5px;'><div style='font-weight: bold;'>{archetype}</div><div>Share: {{c}}%</div>{card_html}</div>"
            }
        })
    
    options = {
        "title": {"text": ""},
        "tooltip": {
            "trigger": "item",
            "backgroundColor": "rgba(30, 30, 30, 0.9)",
            "borderColor": "#333",
            "textStyle": {"color": "#fff"},
            "padding": 5,
            "confine": True,
            "enterable": True,
            "extraCssText": "z-index: 9999; max-width: 300px; white-space: normal;"
        },
        "toolbox": {
            "feature": {
                "saveAsImage": {}
            }
        },
        "legend": {
            "data": list(reversed(sorted_cols)),
            "top": "0%",
            "type": "scroll",
            "textStyle": {"color": "#ccc"}
        },
        "grid": {
            "left": "3%",
            "right": "4%",
            "bottom": "3%",
            "containLabel": True
        },
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": dates,
            "axisLabel": {"color": "#aaa"}
        },
        "yAxis": {
            "type": "value",
            "min": 0,
            "max": 100,
            "axisLabel": {"formatter": "{value}%", "color": "#aaa"},
            "splitLine": {"lineStyle": {"color": "#333"}}
        },
        "series": series
    }
    
    return options

def display_chart(options, height="400px", events=None):
    if options:
        return st_echarts(options=options, height=height, events=events)
    return None

def create_echarts_line_comparison(df, details_map=None, title="", y_axis_label="Share (%)", secondary_df=None, secondary_label=None):
    """
    df: DataFrame where columns are series names and index is dates.
    """
    if df.empty: return None
    
    dates = df.index.tolist()
    show_ja = st.session_state.get("show_japanese_toggle", False)
    series = []
    
    # If we have secondary data, we'll include both in the individual point tooltips
    has_secondary = secondary_df is not None and secondary_label
    
    for col in df.columns:
        # Build card HTML for this archetype
        sig = ""
        match = re.search(r"\(([\da-f]{8})\)$", col)
        if match:
            sig = match.group(1)
        
        if not sig and "Cluster" in col:
             try: sig = col.split("Cluster ")[1].split(")")[0]
             except: pass

        card_html = ""
        if details_map and col in details_map:
             deck = details_map[col]
        elif details_map and sig in details_map:
             deck = details_map[sig]
        else:
             deck = None

        if deck:
            cards = deck.get("cards", [])
            type_order = {"Pokemon": 0, "Goods": 1, "Item": 2, "Stadium": 3, "Support": 4}
            sorted_cards = sorted(cards, key=lambda x: (type_order.get(x.get("type", "Unknown"), 5), x.get("name", "")))
            
            imgs_html = ""
            count = 0
            MAX_IMGS = 20
            for c in sorted_cards:
                if count >= MAX_IMGS: break
                c_set, c_num = c.get("set", ""), c.get("number", "")
                try: p_num = f"{int(c_num):03d}"
                except: p_num = c_num
                img_url = f"{IMAGE_BASE_URL}/{c_set}/{c_set}_{p_num}_EN_SM.webp"
                c_name = get_card_name(c.get("name"), "ja") if show_ja else c.get("name")

                for _ in range(c.get("count", 1)):
                    if count >= MAX_IMGS: break
                    imgs_html += f"<img src='{img_url}' title='{c_name}' style='width: 30px; height: auto; margin: 1px; border-radius: 2px;'>"
                    count += 1
            if imgs_html:
                 card_html = f"<div style='margin-top: 5px; width: 170px; display: flex; flex-wrap: wrap; line-height: 0;'>{imgs_html}</div>"

        # Prepare line data
        line_data = []
        p_label = y_axis_label.replace(" (%)", "")
        s_label = secondary_label if secondary_label else ""
        
        primary_vals = df[col].tolist()
        secondary_vals = secondary_df[col].tolist() if (secondary_df is not None and col in secondary_df.columns) else [None] * len(primary_vals)
        
        for i, (p, s) in enumerate(zip(primary_vals, secondary_vals)):
            p_val = round(p, 2) if pd.notna(p) else None
            
            # If we have secondary data, we create a per-point tooltip
            if has_secondary:
                s_val = round(s, 2) if pd.notna(s) else None
                date_str = dates[i]
                
                # Determine display order: Share should come first
                is_p_share = any(x in p_label for x in ["Share", "シェア"])
                is_s_share = any(x in s_label for x in ["Share", "シェア"])
                
                p_fmt = f"{p_val}%" if p_val is not None else "-"
                s_fmt = f"{s_val}%" if s_val is not None else "-"
                
                if is_s_share and not is_p_share:
                    # Swap display order: Secondary (Share) first
                    v1_label, v1_val = s_label, s_fmt
                    v2_label, v2_val = p_label, p_fmt
                else:
                    # Normal order or both aren't specifically Share/WR
                    v1_label, v1_val = p_label, p_fmt
                    v2_label, v2_val = s_label, s_fmt

                # Construct HTML tooltip for this specific point
                tooltip_str = (
                    f"<div style='font-family: sans-serif; padding: 5px;'>"
                    f"<div style='font-weight: bold;'>{col}</div>"
                    f"<div>{date_str}</div>"
                    f"<div>{v1_label}: {v1_val}</div>"
                    f"<div>{v2_label}: {v2_val}</div>"
                    f"</div>"
                )
                
                line_data.append({
                    "value": p_val,
                    "tooltip": {"formatter": tooltip_str}
                })
            else:
                line_data.append(p_val)

        # Series definition
        p_series = {
            "name": col,
            "type": "line",
            "data": line_data,
            "smooth": True,
            "showSymbol": True,
            "symbol": "circle",
            "symbolSize": 6
        }
        
        if not has_secondary:
            # Metagame Trends fallback: Keep the rich item tooltip at series level
            # This is known to work and contains images.
            p_series["tooltip"] = {
                "formatter": f"<div style='font-family: sans-serif; padding: 5px;'><div style='font-weight: bold;'>{col}</div><div>{y_axis_label}: {{c}}%</div>{card_html}</div>"
            }
            
        series.append(p_series)

    options = {
        "tooltip": {
            "trigger": "item", # Individual points
            "backgroundColor": "rgba(30, 30, 30, 0.9)",
            "borderColor": "#333",
            "textStyle": {"color": "#fff"},
            "padding": 5,
            "confine": True,
            "enterable": True,
            "extraCssText": "z-index: 9999; max-width: 300px; white-space: normal;"
        },
        "legend": {
            "data": df.columns.tolist(),
            "top": "0%",
            "type": "scroll",
            "textStyle": {"color": "#ccc"}
        },
        "grid": {
            "left": "3%", "right": "4%", "bottom": "3%", "top": "12%", "containLabel": True
        },
        "xAxis": {
            "type": "category", 
            "boundaryGap": False, 
            "data": dates,
            "axisLabel": {"color": "#aaa"}
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {"formatter": "{value}", "color": "#aaa"},
            "name": y_axis_label,
            "nameTextStyle": {"color": "#aaa"},
            "splitLine": {"lineStyle": {"color": "#333"}}
        },
        "series": series
    }
    return options
