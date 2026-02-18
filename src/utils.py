
import math
import streamlit as st

def format_deck_name(name):
    # Just capitalize first letter of words
    return name.title()

def format_percentage(val):
    return f"{val:.1f}%"

def calculate_confidence_interval(wins, total, z=1.96):
    """
    Calculate the Wilson score interval for a binomial proportion.
    
    Args:
        wins: Number of successes (wins)
        total: Total number of trials (matches)
        z: Z-score for confidence level (1.96 for 95%)
        
    Returns:
        tuple: (lower_bound_percentage, upper_bound_percentage)
    """
    if total == 0:
        return 0.0, 0.0
        
    p = wins / total
    
    denominator = 1 + z**2 / total
    center_adjusted_probability = p + z**2 / (2 * total)
    adjusted_standard_deviation = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    
    lower_bound = (center_adjusted_probability - adjusted_standard_deviation) / denominator
    upper_bound = (center_adjusted_probability + adjusted_standard_deviation) / denominator
    
    # Clamp to [0, 1] and convert to percentage
    lower_bound = max(0.0, min(lower_bound, 1.0)) * 100
    upper_bound = max(0.0, min(upper_bound, 1.0)) * 100
    
    return lower_bound, upper_bound

def calculate_bayesian_win_probability(wins, total):
    """
    Calculate the probability that the true win rate is > 50% using Bayesian estimation.
    Assumes a Beta(1,1) prior, so the posterior is Beta(wins+1, total-wins+1).
    We use a normal approximation for $P(X > 0.5)$.
    """
    if total == 0:
        return 50.0 # Neutral

    # For Beta(a, b):
    # Mean = a / (a + b)
    # Var = ab / ((a+b)^2 * (a+b+1))
    a = wins + 1
    b = (total - wins) + 1
    
    mean = a / (a + b)
    var = (a * b) / ((a + b)**2 * (a + b + 1))
    sd = math.sqrt(var)
    
    if sd == 0:
        return 100.0 if mean > 0.5 else 0.0
    
    # Z-score for 0.5
    z = (0.5 - mean) / sd
    
    # Normal CDF approximation using erf
    # Phi(x) = 0.5 * (1 + erf(x / sqrt(2)))
    def phi(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    
    # Probability (X > 0.5) = 1 - Phi(z) = Phi(-z)
    prob = phi(-z)
    return prob * 100

def is_local():
    """
    Detect if the application is running in a local/development environment.
    """
    import os
    # Check for common dev environment indicators
    if os.environ.get("IS_LOCAL_DEV") == "true":
        return True
    if os.environ.get("TERM_PROGRAM") == "vscode":
        return True
    
    # Check for DeckGym directory which is usually only mapped in local dev
    if os.path.exists("/workspaces/deckgym-core"):
        return True
        
    return False

def paginate_data(data, page_size=20, key_prefix="pagination"):
    """
    Paginates a list of data using Streamlit session state.

    Args:
        data: List of items to paginate.
        page_size: Number of items per page.
        key_prefix: Unique key prefix for session state to handle multiple paginations.

    Returns:
        tuple: (displayed_data, start_index, end_index, total_rows)
    """
    total_rows = len(data)

    # If no data or fit in one page, return all
    if total_rows <= page_size:
        return data, 0, total_rows, total_rows

    # Current page state
    page_key = f"{key_prefix}_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1

    current_page = st.session_state[page_key]
    total_pages = math.ceil(total_rows / page_size)

    # Validation
    if current_page > total_pages:
        current_page = total_pages
        st.session_state[page_key] = current_page
    if current_page < 1:
        current_page = 1
        st.session_state[page_key] = current_page

    start_index = (current_page - 1) * page_size
    end_index = min(start_index + page_size, total_rows)

    # Slice data
    displayed_data = data[start_index:end_index]

    # Render Pagination Controls
    # Layout: [First] [Prev] [Page Info] [Next] [Last]
    # Adjust column ratios for better alignment
    col1, col2, col3, col4, col5 = st.columns([0.6, 0.6, 1.5, 0.6, 0.6])

    with col1:
        if st.button("First", key=f"{key_prefix}_first", disabled=(current_page == 1)):
            st.session_state[page_key] = 1
            st.rerun()

    with col2:
        if st.button("Prev", key=f"{key_prefix}_prev", disabled=(current_page == 1)):
            st.session_state[page_key] -= 1
            st.rerun()

    with col3:
        st.markdown(
            f"<div style='text-align: center; padding-top: 5px; color: #888; font-size: 0.9em; white-space: nowrap;'>"
            f"Page {current_page} of {total_pages} ({total_rows} items)</div>",
            unsafe_allow_html=True
        )

    with col4:
        if st.button("Next", key=f"{key_prefix}_next", disabled=(current_page == total_pages)):
            st.session_state[page_key] += 1
            st.rerun()

    with col5:
        if st.button("Last", key=f"{key_prefix}_last", disabled=(current_page == total_pages)):
            st.session_state[page_key] = total_pages
            st.rerun()

    return displayed_data, start_index, end_index, total_rows
