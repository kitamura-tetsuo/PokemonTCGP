
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from src.config import CHART_COLORS, PLOTLY_CONFIG

def create_stacked_area_chart(df, title="Metagame Share Over Time"):
    """
    Create a 100% stacked area chart using Plotly.
    
    Args:
        df: DataFrame with dates as index and archetypes as columns.
            Values should be percentages (0-100).
        title: Title for the chart.
    """
    if df.empty:
        return None
        
    fig = go.Figure()
    
    # Sort columns to have popular decks at the top
    latest_shares = df.iloc[-1].sort_values(ascending=False)
    sorted_cols = latest_shares.index.tolist()
    
    for archetype in reversed(sorted_cols): # Reverse to show most popular on top
        values = df[archetype]
        display_name = archetype # Already formatted in data
        
        fig.add_trace(go.Scatter(
            x=df.index,
            y=values,
            name=display_name,
            mode='lines',
            stackgroup='one',
            line=dict(width=0.5),
            hovertemplate='%{y:.1f}%<br>' + display_name + '<extra></extra>'
        ))
        
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Share (%)",
        yaxis=dict(range=[0, 100], ticksuffix='%'),
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=0, r=0, t=50, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=500
    )
    
    return fig

def display_chart(fig, width="stretch"):
    st.plotly_chart(fig, width=width, config=PLOTLY_CONFIG)
