
import logging
import re
import textwrap
import pandas as pd
import streamlit as st
from collections import Counter

from src.data import get_daily_share_data, get_deck_details, get_all_card_names, get_match_history
from src.visualizations import create_stacked_area_chart
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
    # Logic similar to original but using the 'type' field which is already present
    type_order = {
        "Pokemon": 0,
        "Item": 1,
        "Tool": 2,
        "Stadium": 3,
        "Supporter": 4,
        "Unknown": 5,
    }

    # Sort: type_order, then name
    # We assume 'type' is already present in card dict from src.data
    # If not, we default to Unknown
    
    # Ensure all cards have type
    for c in cards:
        if "type" not in c:
            c["type"] = "Unknown"
            
    cards.sort(
        key=lambda x: (type_order.get(x.get("type", "Unknown"), 5), x.get("name", ""))
    )
    return cards

@st.cache_data(ttl=600)
def _get_cached_trend_data(selected_cards, exclude_cards, window):
    # Call the data layer
    # Note: version parameter removed as it was for cache invalidation mainly
    # Convert lists to tuples for hashing if needed, but streamlit handles lists usually
    return get_daily_share_data(
        card_filters=selected_cards, exclude_cards=exclude_cards, window=window
    )

def render_meta_trend_page():
    st.header("Metagame Trends")
    st.markdown(
        "Visualize the evolution of the metagame over time. You can filter by specific cards to see how decks containing them perform."
    )

    # Sidebar / Controls
    with st.expander("Controls", expanded=True):
        col1, col2 = st.columns(2)
        all_cards = get_all_card_names()
        with col1:
            selected_cards = st.multiselect("Filter by Cards (AND)", options=all_cards)
            exclude_cards = st.multiselect("Exclude Cards (NOT)", options=all_cards)

        with col2:
            window = st.slider(
                "Moving Average Window (Days)", min_value=1, max_value=14, value=7
            )

    # Fetch Data
    with st.spinner("Aggregating daily share data..."):
        try:
            df = _get_cached_trend_data(selected_cards, exclude_cards, window)
            
            # If filtered, fetch global data for reference (Diffs)
            global_df = None
            if selected_cards or exclude_cards:
                global_df = _get_cached_trend_data(None, None, window)
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
    """
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

    # Check for Drill-Down
    query_params = st.query_params
    selected_sig = query_params.get("deck_sig", None)
    if selected_sig:
        _render_deck_detail_view(selected_sig)
        return

    # Visualization
    # Clean column names logic: "Name (sig)" -> we keep full name for now
    latest_shares = df.iloc[-1].sort_values(ascending=False)
    MAX_ARCHS = 12
    if len(df.columns) > MAX_ARCHS:
        top_archetypes = latest_shares.index[: MAX_ARCHS - 1].tolist()
        other_archetypes = latest_shares.index[MAX_ARCHS - 1 :].tolist()
        df_display = df[top_archetypes].copy()
        df_display["Others"] = df[other_archetypes].sum(axis=1)
    else:
        df_display = df

    fig = create_stacked_area_chart(
        df_display, title=f"Daily Metagame Share (window={window}d)"
    )
    if fig:
        st.plotly_chart(fig, width="stretch")

    # Table
    st.subheader("Current Metagame Share")
    st.caption("Click headers to sort instantly. Click rows for details.")

    # Prepare Data for Table
    # Extract signatures from column names: "DeckName (sig)"
    sig_map = {}
    for col in df.columns:
        match = re.search(r"\(([\da-f]{8})\)$", col)
        if match:
            sig_map[col] = match.group(1)

    show_diffs = (selected_cards or exclude_cards) and global_df is not None and not global_df.empty
    
    # We need deck details for valid sigs (tooltips, diffs)
    from src.data import get_deck_details_by_signature
    valid_sigs = [s for s in sig_map.values() if s]
    details_map = get_deck_details_by_signature(valid_sigs)
    
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

    # Render Table HTML (simplified)
    # Note: Javascript logic for sorting is copied
    
    diff_headers = ""
    if show_diffs:
        diff_headers = '<th class="header-link">Removed</th><th class="header-link">Added</th>'

    html = textwrap.dedent(
        f"""
<script>
(function() {{
window.jtState = window.jtState || {{ field: 'share', order: 'desc' }};
window.jtSort = function(field) {{
const body = document.getElementById('meta-table-body');
if (!body) return;
const rows = Array.from(body.querySelectorAll('.meta-row-link'));
if (rows.length === 0) return;
if (window.jtState.field === field) {{
window.jtState.order = (window.jtState.order === 'desc') ? 'asc' : 'desc';
}} else {{
window.jtState.field = field;
window.jtState.order = (field === 'name') ? 'asc' : 'desc';
}}
rows.sort((a, b) => {{
let vA = a.getAttribute('data-' + field) || '';
let vB = b.getAttribute('data-' + field) || '';
if (field !== 'name') {{ 
vA = parseFloat(vA) || 0; 
vB = parseFloat(vB) || 0; 
}} else {{
vA = vA.toLowerCase();
vB = vB.toLowerCase();
}}
if (vA < vB) return window.jtState.order === 'asc' ? -1 : 1;
if (vA > vB) return window.jtState.order === 'asc' ? 1 : -1;
return 0;
}});
rows.forEach(r => body.appendChild(r));
window.jtSync();
}};
window.jtSync = function() {{
const fields = ['name', 'share', 'wr', 'matches'];
fields.forEach(f => {{
const ind = document.getElementById('sort-ind-' + f);
if (ind) {{
if (f === window.jtState.field) {{
ind.innerText = (window.jtState.order === 'asc' ? '▲' : '▼');
ind.style.opacity = "1";
ind.parentElement.style.color = "#1ed760";
}} else {{
ind.innerText = '▴▾';
ind.style.opacity = "0.2";
ind.parentElement.style.color = "";
}}
}}
}});
}};
window.initJtTable = function() {{
const fields = ['name', 'share', 'wr', 'matches'];
fields.forEach(f => {{
const el = document.getElementById('header-' + f);
if (el) {{
el.onclick = (e) => {{ 
e.preventDefault(); 
window.jtSort(f); 
}};
}}
}});
window.jtSync();
}};
if (document.readyState === 'complete' || document.readyState === 'interactive') {{
setTimeout(window.initJtTable, 10);
}} else {{
window.addEventListener('load', window.initJtTable);
}}
if (!window.jtObs) {{
window.jtObs = new MutationObserver((mutations) => {{
window.initJtTable();
}});
window.jtObs.observe(document.body, {{ childList: true, subtree: true }});
}}
}})();
</script>
<table class="meta-table">
<thead>
<tr class="meta-header-row">
<th id="header-name" class="header-link">Archetype<span id="sort-ind-name" class="sort-indicator"></span></th>
{diff_headers}
<th id="header-share" class="header-link" style="text-align: right;">Share <span id="sort-ind-share" class="sort-indicator"></span></th>
<th id="header-wr" class="header-link" style="text-align: right;">WinRate <span id="sort-ind-wr" class="sort-indicator"></span></th>
<th id="header-matches" class="header-link" style="text-align: right;">Matches <span id="sort-ind-matches" class="sort-indicator"></span></th>
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
        link = f"?deck_sig={row['sig']}&page=trends" if row["sig"] else "?"
        
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
        st.query_params.clear()
        st.query_params["page"] = "trends"
        st.rerun()

    deck = get_deck_details(sig)
    if not deck:
        st.warning("Deck detail not found.")
        return

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
            cols_per_row = 5
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

            # Build Link
            link = f"?deck_sig={sig}&page=trends"
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

        mdf["Player"] = mdf.apply(lambda r: format_player_link(r, "player"), axis=1)
        mdf["Opponent"] = mdf.apply(lambda r: format_player_link(r, "opponent"), axis=1)
        mdf["Opponent Deck"] = mdf.apply(format_opponent_deck_cell, axis=1)
        
        st.markdown(
            mdf[["date", "tournament", "round", "Player", "Opponent", "Opponent Deck", "result"]].to_html(
                escape=False, index=False
            ),
            unsafe_allow_html=True,
        )
    else:
        st.info("No detailed match records found.")
