import streamlit as st
import pandas as pd
import itertools
from src.data import get_multi_group_trend_data, get_all_card_ids
from src.ui import _get_set_periods, format_card_name, render_filtered_cards
from src.visualizations import display_chart, create_echarts_line_comparison

def render_combinations_page():
    st.header("Card Combination Analysis")
    st.markdown("Analyze how the presence or absence of specific cards impacts deck performance.")

    all_card_ids = get_all_card_ids()

    # --- Query Param Defaults ---
    qp = st.query_params
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
             if q_period in period_options:
                 default_idx = period_options.index(q_period)
             
             selected_period_label = st.selectbox("Aggregation Period", options=period_options, index=default_idx)
             selected_period = next(p for p in periods if p["label"] == selected_period_label)
             standard_only = selected_period["label"] != "All"
        with col2:
             window = st.slider("Moving Average Window (Days)", min_value=1, max_value=14, value=q_window)

    st.divider()

    # --- Global Filters ---
    st.subheader("1. Global Filters")
    st.caption("These conditions apply to ALL generated groups.")
    
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        global_include = st.multiselect("Always Include (AND)", options=all_card_ids, default=q_include, help="Decks must contain ALL of these cards.", format_func=format_card_name)
        render_filtered_cards(global_include)
    with col_g2:
        # Filter options to exclude already included cards
        exclude_options = [c for c in all_card_ids if c not in global_include]
        # Clean default exclude if it conflicts with current include (user interactions)
        curr_exclude_default = [c for c in q_exclude if c in exclude_options]
        
        global_exclude = st.multiselect("Always Exclude (NOT)", options=exclude_options, default=curr_exclude_default, help="Decks must NOT contain ANY of these cards.", format_func=format_card_name)
        render_filtered_cards(global_exclude)

    st.divider()

    # --- Variation Cards ---
    st.subheader("2. Comparison Variables")
    st.caption("Select cards to compare. All meaningful combinations (Presence/Absence) will be analyzed.")
    
    # Filter options
    var_options = [c for c in all_card_ids if c not in global_include and c not in global_exclude]
    curr_vars_default = [c for c in q_vars if c in var_options]

    var_cards = st.multiselect("Select Variables", options=var_options, default=curr_vars_default, format_func=format_card_name)
    render_filtered_cards(var_cards)

    # --- Sync to URL ---
    st.query_params["period"] = selected_period_label
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
        
        if df_share.empty:
            st.warning("No data found matching the criteria.")
        else:
            # Share Chart
            st.subheader("Metagame Share")
            opt_share = create_echarts_line_comparison(df_share, y_axis_label="Share (%)")
            display_chart(opt_share)
            
            # Win Rate Chart
            st.subheader("Win Rate")
            opt_wr = create_echarts_line_comparison(df_wr, y_axis_label="Win Rate (%)")
            display_chart(opt_wr)
            
            # Summary Table
            st.subheader("Period Statistics")
            summary = []
            for g in groups:
                lbl = g["label"]
                if lbl in df_share.columns:
                    avg_share = df_share[lbl].mean()
                    avg_wr = df_wr[lbl].mean()
                    summary.append({
                        "Group": lbl,
                        "Avg Share": f"{avg_share:.2f}%",
                        "Avg Win Rate": f"{avg_wr:.2f}%",
                        "Includes": ", ".join(g["include"]) if len(g["include"]) <= 3 else f"{len(g['include'])} cards",
                        "Excludes": ", ".join(g["exclude"]) if len(g["exclude"]) <= 3 else f"{len(g['exclude'])} cards"
                    })
            if summary:
                st.dataframe(pd.DataFrame(summary), use_container_width=True)
