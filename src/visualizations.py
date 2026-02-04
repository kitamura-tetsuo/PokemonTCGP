import re
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

def create_echarts_line_comparison(df, details_map=None, title="", y_axis_label="Share (%)"):
    """
    df: DataFrame where columns are series names and index is dates.
    """
    if df.empty: return None
    
    dates = df.index.tolist()
    series = []
    
    show_ja = st.session_state.get("show_japanese_toggle", False)
    
    for col in df.columns:
        # Build tooltip content for this archetype (Static HTML Images)
        sig = ""
        match = re.search(r"\(([\da-f]{8})\)$", col)
        if match:
            sig = match.group(1)
        
        # Check clustered format (Name (Cluster ID))
        if not sig and "Cluster" in col:
             try:
                 sig = col.split("Cluster ")[1].split(")")[0]
             except: pass

        card_html = ""
        if details_map and col in details_map: # Check by full name first
             deck = details_map[col]
        elif details_map and sig in details_map: # Then by sig/id if mapped by that (unlikely given ui.py logic but good safety)
             deck = details_map[sig]
        else:
             deck = None

        if deck:
            cards = deck.get("cards", [])
            type_order = {"Pokemon": 0, "Goods": 1, "Item": 2, "Stadium": 3, "Support": 4}
            sorted_cards = sorted(cards, key=lambda x: (type_order.get(x.get("type", "Unknown"), 5), x.get("name", "")))
            
            imgs_html = ""
            count = 0
            MAX_IMGS = 20 # Limit
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

        # Standard ECharts Line
        series.append({
            "name": col,
            "type": "line",
            "data": [round(v, 2) if pd.notna(v) else None for v in df[col].tolist()],
            "smooth": True,
            "showSymbol": True,
            "symbol": "circle",
            "symbolSize": 6,
            "tooltip": {
                "formatter": f"<div style='font-family: sans-serif; padding: 5px;'><div style='font-weight: bold;'>{col}</div><div>{y_axis_label}: {{c}}%</div>{card_html}</div>"
            }
        })
        
    options = {
        # "title": {"text": title, "left": "center", "textStyle": {"color": "#fff"}},
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
