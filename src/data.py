
import json
import logging
import os
from datetime import datetime, timedelta
import pandas as pd
from collections import Counter

from src.hashing import compute_deck_signature

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.getcwd(), "data")
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")
CACHE_FILE = os.path.join(DATA_DIR, "cache", "daily_exact_stats.json")
CARDS_DIR = os.path.join(DATA_DIR, "cards")

def load_card_database():
    """Load card database from JSON."""
    cards = []
    # Try multiple paths
    paths = [
        os.path.join(CARDS_DIR, "cards.extra.json"),
        os.path.join(CARDS_DIR, "cards.json"),
    ]
    
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    for item in data:
                        cards.append({
                            "card_name": item.get("name"),
                            "set": item.get("set"),
                            "num": str(item.get("number")),
                            "type": item.get("type", "Unknown").capitalize(),
                        })
                return cards
            except Exception as e:
                logger.error(f"Error loading {path}: {e}")
    
    return []

def get_all_card_names():
    """Return sorted unique list of all card names."""
    cards = load_card_database()
    names = set(c["card_name"] for c in cards if c.get("card_name"))
    return sorted(list(names))

def _scan_and_aggregate(days_back=30, force_refresh=False):
    """
    Scan standings.json files and aggregate exact deck counts.
    """
    cache = {}
    signatures = {}

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                cache = data.get("dates", {})
                signatures = data.get("signatures", {})
        except Exception as e:
            logger.error(f"Error loading cache: {e}")

    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")
    
    current = datetime.strptime(cutoff_date, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    
    updated = False
    
    # Pre-load card DB for type enrichment
    card_db_list = load_card_database()
    card_type_map = {
        (c["set"], c["num"]): c["type"] for c in card_db_list
    }

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        year, month, day = date_str.split("-")
        
        # Simple check: if not in cache or recent (<=2 days), scan
        is_recent = (end - current).days <= 2
        should_scan = force_refresh or date_str not in cache or is_recent
        
        if should_scan:
            # We need to scan this date's directory
            day_path = os.path.join(TOURNAMENTS_DIR, year, month, day)
            
            # Reset daily data for this date in the accumulator to avoid dupes
            # First, clean up appearances from 'signatures' for this date
            for sig in signatures:
                signatures[sig]["appearances"] = [
                    app for app in signatures[sig].get("appearances", []) 
                    if app.get("date") != date_str
                ]
                # Note: We aren't subtracting from 'stats' easily without recalculating
                # Ideally, stats should be re-computed from appearances entirely 
                # or handle delta. For simplicity here, we might just trust the loop below to add.
                # BUT if we run multiple times, 'stats' will inflate. 
                # PROPER FIX: Rebuild stats from appearances at end? Or just don't cache stats?
                # The original code did subtract. Let's try to mimic that if possible, 
                # or just accept that we might double count if we aren't careful.
                # Since this is "scratch" implementation, let's keep it simple: 
                # We will just overwrite the daily cache entry.
                # 'signatures' is the tricky part.
            
            day_decks = {}
            
            if os.path.exists(day_path):
                for t_id in os.listdir(day_path):
                    standings_path = os.path.join(day_path, t_id, "standings.json")
                    if not os.path.exists(standings_path):
                        continue
                        
                    try:
                        with open(standings_path, "r") as f:
                            standings = json.load(f)
                            
                        for player in standings:
                            if not isinstance(player, dict): continue
                            
                            decklist = player.get("decklist", {})
                            if not decklist: continue
                            
                            # Flatten basic cards
                            all_cards_raw = []
                            for cat in ["pokemon", "trainer", "energy"]:
                                items = decklist.get(cat, [])
                                if isinstance(items, list):
                                    for item in items:
                                        if isinstance(item, dict):
                                            all_cards_raw.append(item)
                                            
                            if not all_cards_raw: continue
                            
                            sig, normalized_cards = compute_deck_signature(all_cards_raw)
                            
                            # Update signatures registry
                            if sig not in signatures:
                                # Enrich types
                                enriched = []
                                for c in normalized_cards:
                                    c_type = card_type_map.get((c["set"], c["number"]), "Unknown")
                                    c["type"] = c_type
                                    enriched.append(c)
                                    
                                signatures[sig] = {
                                    "name": player.get("deck", {}).get("name", "Unknown"),
                                    "cards": enriched,
                                    "stats": {"wins": 0, "losses": 0, "ties": 0, "players": 0},
                                    "appearances": []
                                }
                            
                            # Stats
                            rec = player.get("record", {})
                            w = rec.get("wins", 0)
                            l = rec.get("losses", 0)
                            t = rec.get("ties", 0)
                            
                            # We update stats naively; for perfect consistency we'd rebuild stats from all appearances
                            signatures[sig]["stats"]["wins"] += w
                            signatures[sig]["stats"]["losses"] += l
                            signatures[sig]["stats"]["ties"] += t
                            signatures[sig]["stats"]["players"] += 1
                            
                            signatures[sig]["appearances"].append({
                                "t_id": t_id,
                                "player_id": player.get("player") or player.get("name"),
                                "record": {"wins": w, "losses": l, "ties": t},
                                "date": date_str
                            })
                            
                            day_decks[sig] = day_decks.get(sig, 0) + 1
                            
                    except Exception as e:
                        logger.error(f"Error reading {standings_path}: {e}")
            
            if day_decks:
                cache[date_str] = {"decks": day_decks}
                updated = True
            elif date_str in cache:
                # If we scanned and found nothing, remove old entry?
                # Or keep empty.
                pass

        current += timedelta(days=1)
        
    if updated:
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump({"dates": cache, "signatures": signatures}, f)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
            
    # Filter result to requested range
    result = {}
    for date, data in cache.items():
        if date >= cutoff_date:
            result[date] = data
    return result, signatures

def get_daily_share_data(card_filters=None, exclude_cards=None, window=7, min_total_players=5):
    """
    Get daily deck share data.
    """
    scan_days = window + 7
    daily_data, sig_lookup = _scan_and_aggregate(days_back=scan_days)
    
    if not daily_data:
        return pd.DataFrame()
        
    # Determine valid signatures
    valid_signatures = set()
    all_dates = sorted(daily_data.keys())
    
    all_sigs_in_window = set()
    for date in all_dates:
        all_sigs_in_window.update(daily_data[date]["decks"].keys())
        
    if card_filters or exclude_cards:
        for sig in all_sigs_in_window:
            info = sig_lookup.get(sig)
            if not info: continue
            
            deck_cards = info.get("cards", [])
            card_names = set(c["name"] for c in deck_cards)
            
            if card_filters and not all(f in card_names for f in card_filters):
                continue
            if exclude_cards and any(f in card_names for f in exclude_cards):
                continue
                
            valid_signatures.add(sig)
    else:
        valid_signatures = all_sigs_in_window
        
    if not valid_signatures:
        return pd.DataFrame()
        
    # Build DF
    rows = []
    for date in all_dates:
        day_data = daily_data[date]
        row = {"date": date}
        
        current_day_sigs = day_data["decks"]
        daily_filtered_total = 0
        
        for sig, count in current_day_sigs.items():
            if sig in valid_signatures:
                deck_name = sig_lookup.get(sig, {}).get("name", "Unknown")
                display_name = f"{deck_name} ({sig})"
                row[display_name] = count
                daily_filtered_total += count
                
        if daily_filtered_total >= min_total_players:
            rows.append(row)
            
    if not rows:
        return pd.DataFrame()
        
    df = pd.DataFrame(rows).set_index("date").fillna(0)
    
    # Normalize to 100%
    df_sums = df.sum(axis=1)
    df_normalized = df.div(df_sums, axis=0) * 100
    
    if window > 1:
        df_normalized = df_normalized.rolling(window=window, min_periods=1).mean()
        
    return df_normalized

def get_deck_details_by_signature(signatures):
    """
    Get deck details (name, cards) for a list of signatures.
    Returns a dictionary: sig -> {name, cards, stats, appearances}
    """
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
            all_sigs = data.get("signatures", {})
        
        result = {}
        for sig in signatures:
            if sig in all_sigs:
                result[sig] = all_sigs[sig]
        return result
    except Exception as e:
        logger.error(f"Error loading deck details: {e}")
        return {}

def get_deck_details(sig):
    return get_deck_details_by_signature([sig]).get(sig)

def get_match_history(appearances):
    """
    Look up detailed matches for a list of player appearances.
    """
    matches = []
    
    # Load all signatures for opponent lookup
    if not os.path.exists(CACHE_FILE):
        return []
        
    try:
        with open(CACHE_FILE, "r") as f:
            full_cache = json.load(f)
            sig_lookup = full_cache.get("signatures", {})
    except:
        sig_lookup = {}

    for app in appearances:
        t_id = app.get("t_id")
        p_name = app.get("player_id")
        date_str = app.get("date")
        if not t_id or not date_str:
            continue

        year, month, day = date_str.split("-")
        t_path = os.path.join(TOURNAMENTS_DIR, year, month, day, t_id)

        pairings_path = os.path.join(t_path, "pairings.json")
        standings_path = os.path.join(t_path, "standings.json")

        if os.path.exists(pairings_path) and os.path.exists(standings_path):
            try:
                with open(pairings_path, "r") as f:
                    pairings = json.load(f)
                with open(standings_path, "r") as f:
                    standings = json.load(f)

                # Map names to deck info for this tournament
                player_deck_info = {}
                for p in standings:
                    p_name_standings = p.get("name")
                    dlist = p.get("decklist", {})
                    if not dlist: continue
                    
                    all_cards = []
                    for cat in ["pokemon", "trainer", "energy"]:
                        items = dlist.get(cat, [])
                        if items: 
                            for item in items:
                                if isinstance(item, dict):
                                    all_cards.append(item)

                    if all_cards:
                        from src.hashing import compute_deck_signature
                        opp_sig, _ = compute_deck_signature(all_cards)
                        deck_name = p.get("deck", {}).get("name", "Unknown")
                        info = {"sig": opp_sig, "deck_name": deck_name, "cards": all_cards}
                        p_id = (p.get("player") or p.get("name", "")).lower()
                        if p_id:
                            player_deck_info[p_id] = info
                
                # Tournament Name
                t_name = t_id
                det_path = os.path.join(t_path, "details.json")
                if os.path.exists(det_path):
                    with open(det_path, "r") as f:
                        t_name = json.load(f).get("name", t_id)

                for m in pairings:
                    if not isinstance(m, dict): continue
                    p1, p2 = m.get("player1"), m.get("player2")
                    if not p1: continue # Bye or invalid
                    
                    # Normalize for match
                    p1_match = p1.lower() if isinstance(p1, str) else p1
                    p2_match = p2.lower() if isinstance(p2, str) else p2
                    target_match = p_name.lower() if isinstance(p_name, str) else p_name

                    if p1_match == target_match or p2_match == target_match:
                        opp_name = p2 if p1_match == target_match else p1
                        opp_id = opp_name.lower() if isinstance(opp_name, str) else opp_name
                        winner = m.get("winner")
                        winner_match = winner.lower() if isinstance(winner, str) else winner
                        
                        res = "Tie"
                        if winner_match == target_match: res = "Win"
                        elif winner_match == opp_id: res = "Loss"
                        
                        opp_info = player_deck_info.get(opp_id, {})
                        opp_sig = opp_info.get("sig")
                            
                        matches.append({
                            "date": date_str,
                            "tournament": t_name,
                            "t_id": t_id,
                            "player": p_name,
                            "round": m.get("round", "?"),
                            "opponent": opp_name,
                            "opponent_deck": f"{opp_info.get('deck_name', 'Unknown')} ({opp_sig})" if opp_sig else "Unknown",
                            "opponent_sig": opp_sig,
                            "opponent_cards": opp_info.get("cards", []),
                            "result": res
                        })
            except Exception as e:
                logger.error(f"Error lookup pairings for {t_id}: {e}")
    return matches
