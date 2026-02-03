
import json
import logging
import os
import re
from datetime import datetime, timedelta
import pandas as pd
from collections import Counter

from src.hashing import compute_deck_signature

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.getcwd(), "data")
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")
CACHE_FILE = os.path.join(DATA_DIR, "cache", "daily_exact_stats.json")
CLUSTERS_FILE = os.path.join(DATA_DIR, "cache", "clusters.json")
CARDS_DIR = os.path.join(DATA_DIR, "cards")

def _normalize_type(t):
    """Normalize various type names to a consistent set: Pokemon, Goods, Item, Stadium, Support."""
    if not t:
        return "Unknown"
    t = t.lower().strip()
    if t in ["pokemon", "pokemon (heuristic)"]:
        return "Pokemon"
    if t in ["goods", "item", "item (heuristic)"]:
        # Note: 'item' in JSON often means 'Goods'. 
        # But user uses 'Item' for Tools in CSV.
        # So we prioritize user's CSV mapping if we can.
        return "Goods"
    if t in ["tool", "item"]: # Fallback
        return "Item"
    if t in ["supporter", "support"]:
        return "Support"
    if t in ["stadium"]:
        return "Stadium"
    return t.capitalize()

def load_card_database():
    """Load card database from JSON."""
    cards = []
    
    # Load unknown cards CSV if exists
    unknown_csv = os.path.join(CARDS_DIR, "unknown_cards.csv")
    csv_overrides = {}
    if os.path.exists(unknown_csv):
        try:
            import csv
            with open(unknown_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    c_set = row.get("set")
                    c_num = row.get("number")
                    manual_type = row.get("manual_type")
                    if c_set and c_num and manual_type:
                        # User's manual type is prioritized and normalized
                        t = manual_type.strip()
                        if t:
                            # Direct mapping for user terms
                            if t.lower() == "goods": normalized = "Goods"
                            elif t.lower() == "item": normalized = "Item"
                            elif t.lower() == "support": normalized = "Support"
                            elif t.lower() == "stadium": normalized = "Stadium"
                            else: normalized = _normalize_type(t)
                            csv_overrides[(c_set, str(c_num))] = normalized
        except Exception as e:
            logger.error(f"Error loading unknown_cards.csv: {e}")

    cards_map = {}
    
    # Reorder paths to load main first, then extra (so extra overrides)
    paths = [
        os.path.join(CARDS_DIR, "cards.json"),
        os.path.join(CARDS_DIR, "cards.extra.json"),
    ]

    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    for item in data:
                        c_set = item.get("set")
                        c_num = str(item.get("number"))
                        cards_map[(c_set, c_num)] = item
            except Exception as e:
                logger.error(f"Error loading {path}: {e}")
    
    # Now process the merged map
    for (c_set, c_num), item in cards_map.items():
        # Priority 1: CSV Override
        c_type = csv_overrides.get((c_set, c_num))
        
        # Priority 2: JSON Type
        if not c_type:
            c_type = item.get("type")
            if c_type:
                # Standard JSON types like 'item' -> 'Goods'
                c_type = _normalize_type(c_type)
        
        # Priority 3: Image Heuristic
        if not c_type or c_type == "Unknown":
            img = item.get("image", "")
            if img.startswith("cPK"):
                c_type = "Pokemon"
            elif img.startswith("cTR"):
                c_type = "Goods" # Default generic trainer/item
        
        cards.append({
            "card_name": item.get("name"),
            "set": c_set,
            "num": c_num,
            "type": c_type or "Unknown",
            "image": item.get("image")
        })

    return cards

def enrich_card_data(cards):
    """
    Enrich a list of card dictionaries with the latest type information from the database.
    This fixes 'Unknown' types in cached data.
    """
    db_cards = load_card_database()
    # Build a lookup map: (set, number) -> {type, image}
    card_lookup = {
        (c.get("set"), str(c.get("num"))): {
            "type": c.get("type"),
            "image": c.get("image")
        } for c in db_cards if c.get("set") and c.get("num")
    }
    
    # Load CSV overrides explicitly
    unknown_csv = os.path.join(CARDS_DIR, "unknown_cards.csv")
    csv_overrides = {}
    if os.path.exists(unknown_csv):
        try:
            import csv
            with open(unknown_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    c_set = row.get("set")
                    c_num = row.get("number")
                    manual_type = row.get("manual_type")
                    if c_set and c_num and manual_type:
                        t = manual_type.strip()
                        if t:
                            if t.lower() == "goods": normalized = "Goods"
                            elif t.lower() == "item": normalized = "Item"
                            elif t.lower() == "support": normalized = "Support"
                            elif t.lower() == "stadium": normalized = "Stadium"
                            else: normalized = _normalize_type(t)
                            csv_overrides[(c_set, str(c_num))] = normalized
        except: pass

    enriched = []
    for c in cards:
        new_c = c.copy()
        key = (new_c.get("set"), str(new_c.get("number")))
        
        db_info = card_lookup.get(key, {})
        
        # Priority 1: CSV Override for Type
        if key in csv_overrides:
            new_c["type"] = csv_overrides[key]
        elif db_info.get("type"):
            new_c["type"] = _normalize_type(db_info["type"])
        else:
            # Fallback normalization of existing type
            new_c["type"] = _normalize_type(new_c.get("type", "Unknown"))
            
        # Prioritize image from DB if available
        if db_info.get("image"):
            new_c["image"] = db_info["image"]
        
        # Final heuristic fallback for type if still Unknown
        if new_c.get("type") == "Unknown":
            img = new_c.get("image", "")
            if img.startswith("cPK"):
                new_c["type"] = "Pokemon"
            elif img.startswith("cTR"):
                new_c["type"] = "Goods"

        enriched.append(new_c)
    return enriched

def get_all_card_names():
    """Return sorted unique list of all card names."""
    cards = load_card_database()
    names = set(c["card_name"] for c in cards if c.get("card_name"))
    return sorted(list(names))

def _scan_and_aggregate(days_back=30, force_refresh=False, start_date=None, end_date=None):
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

    # Determine date range to scan
    today_dt = datetime.now()
    if start_date:
        cutoff_date = start_date
    else:
        cutoff_date = (today_dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    if end_date:
        last_date = end_date
    else:
        last_date = today_dt.strftime("%Y-%m-%d")
    
    current = datetime.strptime(cutoff_date, "%Y-%m-%d")
    end = datetime.strptime(last_date, "%Y-%m-%d")
    
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
        # Note: We also scan if the cache entry is in the OLD format (has 'decks' but no 'tournaments')
        is_recent = (today_dt - current).days <= 2
        entry = cache.get(date_str, {})
        is_old_format = "decks" in entry and "tournaments" not in entry
        should_scan = force_refresh or date_str not in cache or is_recent or is_old_format
        
        if should_scan:
            day_path = os.path.join(TOURNAMENTS_DIR, year, month, day)
            day_tournaments = {}
            
            if os.path.exists(day_path):
                # Before scanning this date, remove existing appearances for this date to avoid dupes
                for sig in signatures:
                    signatures[sig]["appearances"] = [
                        app for app in signatures[sig].get("appearances", []) 
                        if app.get("date") != date_str
                    ]

                for t_id in os.listdir(day_path):
                    t_dir = os.path.join(day_path, t_id)
                    standings_path = os.path.join(t_dir, "standings.json")
                    details_path = os.path.join(t_dir, "details.json")
                    
                    if not os.path.exists(standings_path):
                        continue
                        
                    # Get tournament format
                    t_format = None
                    if os.path.exists(details_path):
                        try:
                            with open(details_path, "r") as dfp:
                                det = json.load(dfp)
                                t_format = det.get("format")
                        except: pass
                    
                    try:
                        with open(standings_path, "r") as f:
                            standings = json.load(f)
                            
                        t_decks = {}
                        for player in standings:
                            if not isinstance(player, dict): continue
                            
                            decklist = player.get("decklist", {})
                            if not decklist: continue
                            
                            all_cards_raw = []
                            for cat in ["pokemon", "trainer", "energy"]:
                                items = decklist.get(cat, [])
                                if isinstance(items, list):
                                    for item in items:
                                        if isinstance(item, dict):
                                            all_cards_raw.append(item)
                                            
                            if not all_cards_raw: continue
                            
                            sig, normalized_cards = compute_deck_signature(all_cards_raw)
                            
                            if sig not in signatures:
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
                            
                            rec = player.get("record", {})
                            w, l, t = rec.get("wins", 0), rec.get("losses", 0), rec.get("ties", 0)
                            
                            # Stats are re-derived from appearances at the end to avoid double-counting
                            
                            signatures[sig]["appearances"].append({
                                "t_id": t_id,
                                "player_id": player.get("player") or player.get("name"),
                                "record": {"wins": w, "losses": l, "ties": t},
                                "date": date_str
                            })
                            
                            t_decks[sig] = t_decks.get(sig, 0) + 1
                        
                        if t_decks:
                            day_tournaments[t_id] = {"format": t_format, "decks": t_decks}
                            
                    except Exception as e:
                        logger.error(f"Error reading {standings_path}: {e}")
            
            if day_tournaments:
                cache[date_str] = {"tournaments": day_tournaments}
                updated = True
            elif date_str in cache:
                # If we scanned and found nothing, but it was there before, we might want to keep it or clear it.
                # For safety, if we explicitly scanned and found nothing, it means data is gone.
                pass

        current += timedelta(days=1)
        
    # Recalculate all stats from appearances to ensure consistency and avoid double-counting
    for sig in signatures:
        apps = signatures[sig].get("appearances", [])
        w_total = sum(app.get("record", {}).get("wins", 0) for app in apps)
        l_total = sum(app.get("record", {}).get("losses", 0) for app in apps)
        t_total = sum(app.get("record", {}).get("ties", 0) for app in apps)
        signatures[sig]["stats"] = {
            "wins": w_total,
            "losses": l_total,
            "ties": t_total,
            "players": len(apps)
        }
    
    # We always set updated to True if we are doing a scan that involves recalculation 
    # to ensure the corrected stats are saved.
    if force_refresh:
        updated = True
        
    if updated:
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            temp_file = CACHE_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump({"dates": cache, "signatures": signatures}, f)
            os.replace(temp_file, CACHE_FILE)
            
            # Clear internal cache to force reload
            global _SIGNATURES_CACHE
            _SIGNATURES_CACHE = None 
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
            
    return cache, signatures

def get_daily_share_data(card_filters=None, exclude_cards=None, window=7, min_total_players=5, start_date=None, end_date=None, standard_only=False):
    """
    Get daily deck share data.
    """
    # Scan a bit more than window to allow rolling mean calculation if needed
    # If explicit dates provided, we use them.
    scan_start = start_date
    if not scan_start:
        scan_days = window + 7
        scan_start = (datetime.now() - timedelta(days=scan_days)).strftime("%Y-%m-%d")

    daily_raw, sig_lookup = _scan_and_aggregate(start_date=scan_start, end_date=end_date)
    
    if not daily_raw:
        return pd.DataFrame()
        
    all_dates = sorted(daily_raw.keys())
    
    # Filter and aggregate daily_raw into a cleaner daily format: date -> {sig: count}
    daily_aggregated = {}
    valid_signatures_meta = set() # To identify which sigs exist in the filtered set

    for date_str in all_dates:
        if start_date and date_str < start_date: continue
        if end_date and date_str > end_date: continue
        
        day_entry = daily_raw[date_str]
        day_decks = Counter()
        
        # Support both old and new cache format for robustness during transition
        if "tournaments" in day_entry:
            for t_id, t_data in day_entry["tournaments"].items():
                if standard_only and t_data.get("format") is not None:
                    continue
                day_decks.update(t_data.get("decks", {}))
        elif "decks" in day_entry:
            # Old format doesn't have format info, include if not standard_only
            if not standard_only:
                day_decks.update(day_entry["decks"])
        
        if day_decks:
            daily_aggregated[date_str] = day_decks
            valid_signatures_meta.update(day_decks.keys())

    if not daily_aggregated:
        return pd.DataFrame()

    # Convert to DataFrame
    df = pd.DataFrame.from_dict(daily_aggregated, orient='index').fillna(0)
    
    # Calculate daily totals for meta-share normalization (BEFORE filtering)
    daily_metagame_totals = df.sum(axis=1)

    # Filter columns by card criteria
    final_cols = []
    for sig in df.columns:
        info = sig_lookup.get(sig)
        if not info: continue
        
        card_names = set(c["name"] for c in info.get("cards", []))
        if card_filters and not all(f in card_names for f in card_filters):
            continue
        if exclude_cards and any(f in card_names for f in exclude_cards):
            continue
        
        final_cols.append(sig)
    
    if not final_cols:
        return pd.DataFrame()
        
    df = df[final_cols]
    
    # Rename columns to display format f"{name} ({sig})"
    df.columns = [f"{sig_lookup.get(s, {}).get('name', 'Unknown')} ({s})" for s in df.columns]

    # Normalize by the sum of FILTERED decks on each day (back to 100% within the view)
    df_normalized = df.div(df.sum(axis=1), axis=0) * 100
    
    if window > 1:
        df_normalized = df_normalized.rolling(window=window, min_periods=1).mean()
    
    if min_total_players > 0:
        # We still filter by daily_metagame_totals to ensure volume, but normalization is relative
        df_normalized = df_normalized[daily_metagame_totals >= min_total_players]

    return df_normalized

# Global variable to cache the signatures part of the JSON to avoid repetitive large reads
_SIGNATURES_CACHE = None
_CACHE_MTIME = 0

def _get_all_signatures():
    """Internal helper to load and cache all signatures from the large JSON file."""
    global _SIGNATURES_CACHE, _CACHE_MTIME
    if not os.path.exists(CACHE_FILE):
        return {}
    
    mtime = os.path.getmtime(CACHE_FILE)
    if _SIGNATURES_CACHE is not None and mtime == _CACHE_MTIME:
        return _SIGNATURES_CACHE
    
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
            _SIGNATURES_CACHE = data.get("signatures", {})
            _CACHE_MTIME = mtime
        return _SIGNATURES_CACHE
    except Exception as e:
        logger.error(f"Error loading cache for signatures: {e}")
        return _SIGNATURES_CACHE or {}

def get_deck_details_by_signature(signatures, start_date=None, end_date=None):
    """
    Get deck details (name, cards) for a list of signatures.
    If dates are provided, statistics are filtered to that period.
    Returns a dictionary: sig -> {name, cards, stats, appearances}
    """
    all_sigs = _get_all_signatures()
    result = {}
    for sig in signatures:
        if sig in all_sigs:
            info = all_sigs[sig].copy()
            
            # Filter appearances and recalculate stats if dates provided
            if start_date or end_date:
                apps = info.get("appearances", [])
                filtered_apps = []
                for app in apps:
                    date = app.get("date")
                    if start_date and date < start_date: continue
                    if end_date and date > end_date: continue
                    filtered_apps.append(app)
                
                w = sum(a.get("record", {}).get("wins", 0) for a in filtered_apps)
                l = sum(a.get("record", {}).get("losses", 0) for a in filtered_apps)
                t = sum(a.get("record", {}).get("ties", 0) for a in filtered_apps)
                
                info["appearances"] = filtered_apps
                info["stats"] = {
                    "wins": w,
                    "losses": l,
                    "ties": t,
                    "players": len(filtered_apps)
                }
            
            result[sig] = info
    return result

def get_deck_details(sig, start_date=None, end_date=None):
    return get_deck_details_by_signature([sig], start_date=start_date, end_date=end_date).get(sig)

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

# Global variable to cache cluster mapping
_SIG_TO_CLUSTER = None
_ID_TO_CLUSTER = None
_CLUSTERS_MTIME = 0

def get_cluster_mapping():
    """Returns a map of sig -> cluster_info and cluster_id -> cluster_info."""
    global _SIG_TO_CLUSTER, _ID_TO_CLUSTER, _CLUSTERS_MTIME
    if not os.path.exists(CLUSTERS_FILE):
        return {}, {}
    
    mtime = os.path.getmtime(CLUSTERS_FILE)
    if _SIG_TO_CLUSTER is not None and mtime == _CLUSTERS_MTIME:
        return _SIG_TO_CLUSTER, _ID_TO_CLUSTER
    
    try:
        with open(CLUSTERS_FILE, "r") as f:
            clusters = json.load(f)
        
        _SIG_TO_CLUSTER = {}
        _ID_TO_CLUSTER = {}
        for c in clusters:
            cid = str(c["id"])
            _ID_TO_CLUSTER[cid] = c
            for sig in c["signatures"]:
                _SIG_TO_CLUSTER[sig] = c
        
        _CLUSTERS_MTIME = mtime
        return _SIG_TO_CLUSTER, _ID_TO_CLUSTER
    except Exception as e:
        logger.error(f"Error loading clusters: {e}")
        return {}, {}

def get_clustered_daily_share_data(card_filters=None, exclude_cards=None, window=7, min_total_players=5, start_date=None, end_date=None, standard_only=False):
    """
    Get daily deck share data aggregated by cluster.
    """
    scan_start = start_date
    if not scan_start:
        scan_days = window + 7
        scan_start = (datetime.now() - timedelta(days=scan_days)).strftime("%Y-%m-%d")

    daily_raw, sig_lookup = _scan_and_aggregate(start_date=scan_start, end_date=end_date)
    sig_to_cluster, _ = get_cluster_mapping()
    
    if not daily_raw:
        return pd.DataFrame()
        
    all_dates = sorted(daily_raw.keys())
    daily_aggregated = {}
    valid_clusters = set()

    for date_str in all_dates:
        if start_date and date_str < start_date: continue
        if end_date and date_str > end_date: continue
        
        day_entry = daily_raw[date_str]
        
        # Aggregate by cluster
        cluster_counts = Counter()
        
        t_data_list = []
        if "tournaments" in day_entry:
            for t_id, t_data in day_entry["tournaments"].items():
                if standard_only and t_data.get("format") is not None:
                    continue
                for sig, count in t_data.get("decks", {}).items():
                    c_info = sig_to_cluster.get(sig)
                    c_label = f"{c_info['representative_name']} (Cluster {c_info['id']})" if c_info else f"Unclustered ({sig})"
                    cluster_counts[c_label] += count
                    
                    # Store which sigs are in this cluster for filtering
                    valid_clusters.add(c_label)
        elif "decks" in day_entry and not standard_only:
            for sig, count in day_entry["decks"].items():
                c_info = sig_to_cluster.get(sig)
                c_label = f"{c_info['representative_name']} (Cluster {c_info['id']})" if c_info else f"Unclustered ({sig})"
                cluster_counts[c_label] += count
                valid_clusters.add(c_label)
        
        if cluster_counts:
            daily_aggregated[date_str] = cluster_counts

    if not daily_aggregated:
        return pd.DataFrame()

    # Convert to DataFrame
    df = pd.DataFrame.from_dict(daily_aggregated, orient='index').fillna(0)
    
    # Calculate daily totals for meta-share normalization (BEFORE filtering)
    daily_metagame_totals = df.sum(axis=1)

    # Filter by cards if requested
    if card_filters or exclude_cards:
        # Pre-calculate which signatures match
        matching_sigs = set()
        for sig, info in sig_lookup.items():
            card_names = set(c["name"] for c in info.get("cards", []))
            if card_filters and not all(f in card_names for f in card_filters):
                continue
            if exclude_cards and any(f in card_names for f in exclude_cards):
                continue
            matching_sigs.add(sig)
            
        _, id_to_cluster = get_cluster_mapping()
        filtered_labels = set()
        for label in df.columns:
            if "Cluster" in label:
                cid = label.split("Cluster ")[1].split(")")[0]
                c_info = id_to_cluster.get(cid)
                if c_info and any(s in matching_sigs for s in c_info["signatures"]):
                    filtered_labels.add(label)
            else:
                match = re.search(r"\(([\da-f]{8})\)$", label)
                if match and match.group(1) in matching_sigs:
                    filtered_labels.add(label)
        
        if not filtered_labels:
            return pd.DataFrame()
        df = df[list(filtered_labels)]
        
    # Normalize by the sum of FILTERED clusters on each day (back to 100% within the view)
    df_normalized = df.div(df.sum(axis=1), axis=0) * 100
    
    if window > 1:
        df_normalized = df_normalized.rolling(window=window, min_periods=1).mean()
    
    if min_total_players > 0:
        df_normalized = df_normalized[daily_metagame_totals >= min_total_players]

    return df_normalized

def get_cluster_details(cluster_id, start_date=None, end_date=None):
    """Get aggregated details for a cluster, optionally filtered by date."""
    _, id_to_cluster = get_cluster_mapping()
    c_info = id_to_cluster.get(str(cluster_id))
    if not c_info:
        return None
    
    signatures = get_deck_details_by_signature(c_info["signatures"], start_date=start_date, end_date=end_date)
    
    # Aggregate stats from filtered signatures
    total_stats = {"wins": 0, "losses": 0, "ties": 0, "players": 0}
    all_apps = []
    
    for sig in signatures:
        s = signatures[sig].get("stats", {})
        for k in total_stats:
            total_stats[k] += s.get(k, 0)
        all_apps.extend(signatures[sig].get("appearances", []))
        
    # Get cards from representative deck or ANY available deck in the cluster
    rep_sig = c_info["representative_sig"]
    rep_cards = []
    
    # Check if rep sig is in our already-fetched list
    if rep_sig in signatures:
        rep_cards = signatures[rep_sig].get("cards", [])
    else:
        # Fallback: Use cards from the first available signature
        # We prefer the one with the most matches if possible, but any is better than none
        if signatures:
             # Sort by # of players or matches to pick a "good" representative?
             # For now just pick the first one to ensure we show cards
             fallback_sig = next(iter(signatures))
             rep_cards = signatures[fallback_sig].get("cards", [])
             # Update representative sig in return object so UI knows?
             # Actually UI uses "representative_sig" from the return dict if we wanted to change it.
             # But let's just populate "cards".
             rep_sig = fallback_sig

    return {
        "id": cluster_id,
        "name": c_info["representative_name"],
        "representative_sig": rep_sig,
        "stats": total_stats,
        "appearances": all_apps,
        "signatures": signatures, # sig -> details (already filtered)
        "cards": rep_cards
    }

def get_multi_group_trend_data(groups, window=7, start_date=None, end_date=None, standard_only=False):
    """
    groups: List of dicts, e.g. [{"label": "A+B", "include": ["card1"], "exclude": ["card2"]}]
    Returns: {
        "share": pd.DataFrame (cols=labels),
        "wr": pd.DataFrame (cols=labels),
        "totals": pd.Series (daily match totals)
    }
    """
    scan_start = start_date
    if not scan_start:
        scan_days = window + 7
        scan_start = (datetime.now() - timedelta(days=scan_days)).strftime("%Y-%m-%d")

    daily_raw, sig_lookup = _scan_and_aggregate(start_date=scan_start, end_date=end_date)
    
    if not daily_raw:
        return {"share": pd.DataFrame(), "wr": pd.DataFrame(), "totals": pd.Series()}

    all_dates = sorted(daily_raw.keys())
    
    # 1. Calculate Daily Totals (Denominator for Share)
    daily_totals = {}
    for date_str in all_dates:
        if start_date and date_str < start_date: continue
        if end_date and date_str > end_date: continue
        
        day_entry = daily_raw[date_str]
        day_total = 0
        
        if "tournaments" in day_entry:
            for t_id, t_data in day_entry["tournaments"].items():
                if standard_only and t_data.get("format") is not None:
                    continue
                day_total += sum(t_data.get("decks", {}).values())
        elif "decks" in day_entry:
             if not standard_only:
                day_total += sum(day_entry["decks"].values())
        
        daily_totals[date_str] = day_total

    # 2. Map Signatures to Groups
    sig_to_groups = {}
    for sig, info in sig_lookup.items():
        deck_cards = set(c["name"] for c in info.get("cards", []))
        matched_groups = []
        for g in groups:
            inc = g.get("include", [])
            exc = g.get("exclude", [])
            
            has_inc = not inc or all(c in deck_cards for c in inc)
            has_exc = exc and any(c in deck_cards for c in exc)
            
            if has_inc and not has_exc:
                matched_groups.append(g["label"])
        
        if matched_groups:
            sig_to_groups[sig] = matched_groups

    # 3. Aggregate Stats by Group by Day
    # label -> date -> {wins, losses, count}
    # Pre-fill
    group_daily_agg = {g["label"]: {d: {"wins": 0, "losses": 0, "ties": 0, "count": 0} for d in daily_totals} for g in groups}

    for sig, labels in sig_to_groups.items():
        info = sig_lookup.get(sig)
        if not info: continue
        
        apps = info.get("appearances", [])
        for app in apps:
            d = app.get("date")
            if d not in daily_totals: continue
            
            rec = app.get("record", {})
            w, l, t = rec.get("wins", 0), rec.get("losses", 0), rec.get("ties", 0)
            
            for label in labels:
                entry = group_daily_agg[label][d]
                entry["wins"] += w
                entry["losses"] += l
                entry["ties"] += t
                entry["count"] += 1

    # 4. Build DataFrames
    share_data = {}
    wr_data = {}
    
    for label in group_daily_agg:
        shares = {}
        wrs = {}
        for d, stats in group_daily_agg[label].items():
            total_matches = stats["wins"] + stats["losses"] + stats["ties"]
            wr = (stats["wins"] / total_matches * 100) if total_matches > 0 else 0
            
            day_total = daily_totals.get(d, 0)
            share = (stats["count"] / day_total * 100) if day_total > 0 else 0
            
            shares[d] = share
            wrs[d] = wr
            
        share_data[label] = shares
        wr_data[label] = wrs
        
    df_share = pd.DataFrame(share_data).fillna(0)
    df_wr = pd.DataFrame(wr_data).fillna(0)
    
    if window > 1:
        df_share = df_share.rolling(window=window, min_periods=1).mean()
        df_wr = df_wr.rolling(window=window, min_periods=1).mean()
        
    return {
        "share": df_share, 
        "wr": df_wr, 
        "totals": pd.Series(daily_totals)
    }

def get_period_statistics(df, start_date=None, end_date=None, clustered=False):
    """
    Calculate period-wide statistics from the daily share dataframe and total counts.
    Returns: { label: { avg_share, total_stats } }
    """
    if df.empty:
        return {}
    
    # We aggregate stats (Matches, Players, WR)
    stats_map = {}
    from src.data import get_cluster_details, get_deck_details
    
    total_period_players_in_view = 0
    all_details = {}
    
    for label in df.columns:
        if clustered:
            if "Cluster" in label:
                cid = label.split("Cluster ")[1].split(")")[0]
                details = get_cluster_details(cid, start_date=start_date, end_date=end_date)
            else:
                match = re.search(r"\((\w+)\)$", label)
                sig = match.group(1) if match else None
                details = get_deck_details(sig, start_date=start_date, end_date=end_date) if sig else None
        else:
            match = re.search(r"\((\w+)\)$", label)
            sig = match.group(1) if match else None
            details = get_deck_details(sig, start_date=start_date, end_date=end_date) if sig else None
        
        if details:
            all_details[label] = details
            total_period_players_in_view += details.get("stats", {}).get("players", 0)
            
    for label, details in all_details.items():
        deck_players = details.get("stats", {}).get("players", 0)
        avg_share = (deck_players / total_period_players_in_view * 100) if total_period_players_in_view > 0 else 0
        
        stats_map[label] = {
            "avg_share": avg_share,
            "stats": details.get("stats", {}),
            "deck_info": details
        }
            
    return stats_map
