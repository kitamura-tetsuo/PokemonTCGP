import os
import json
import logging
import pandas as pd
from datetime import datetime
from collections import Counter, defaultdict
from src.data import load_enriched_sets, get_deck_details_by_signature, _scan_and_aggregate
from src.hashing import compute_deck_signature
from src.simulator import run_simulation, convert_signature_to_deckgym
from scipy.stats import chi2_contingency

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = "/workspaces/PokemonTCGP/data"
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")
CACHE_DIR = os.path.join(DATA_DIR, "matchup_analysis")
SIMULATION_CACHE_FILE = os.path.join(CACHE_DIR, "simulation_cache.json")
TOP_MATCHUPS_CACHE_FILE = os.path.join(CACHE_DIR, "top_matchups_cache.json")

os.makedirs(CACHE_DIR, exist_ok=True)

def get_set_periods():
    """Returns a list of periods based on set release dates."""
    enriched_sets = load_enriched_sets()
    # Sort by release date ascending
    chronological_sets = sorted(enriched_sets, key=lambda x: x.get("releaseDate", "9999-99-99"))
    
    periods = []
    for i in range(len(chronological_sets)):
        s = chronological_sets[i]
        start = s.get("releaseDate")
        name = s.get("name_en") or s.get("code")
        
        end = None
        if i < len(chronological_sets) - 1:
            end_dt = datetime.strptime(chronological_sets[i+1]["releaseDate"], "%Y-%m-%d")
            # End is the day before the next release
            from datetime import timedelta
            end = (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        
        periods.append({
            "name": name,
            "start": start,
            "end": end,
            "code": s.get("code")
        })
    # Newest first
    periods.reverse()
    return periods

def get_all_pairings():
    """
    Generator that yields all pairings found in the tournament data.
    Yields: (date, p1_sig, p2_sig, winner_id)
    """
    # We can use the information from standings.json to get signatures for player names
    for year in sorted(os.listdir(TOURNAMENTS_DIR)):
        year_path = os.path.join(TOURNAMENTS_DIR, year)
        if not os.path.isdir(year_path): continue
        for month in sorted(os.listdir(year_path)):
            month_path = os.path.join(year_path, month)
            if not os.path.isdir(month_path): continue
            for day in sorted(os.listdir(month_path)):
                day_path = os.path.join(month_path, day)
                if not os.path.isdir(day_path): continue
                date_str = f"{year}-{month}-{day}"
                for t_id in os.listdir(day_path):
                    t_dir = os.path.join(day_path, t_id)
                    standings_path = os.path.join(t_dir, "standings.json")
                    pairings_path = os.path.join(t_dir, "pairings.json")
                    
                    if not (os.path.exists(standings_path) and os.path.exists(pairings_path)):
                        continue
                        
                    try:
                        with open(standings_path, "r") as f:
                            standings = json.load(f)
                        with open(pairings_path, "r") as f:
                            pairings = json.load(f)
                            
                        # Map player names to signatures
                        player_to_sig = {}
                        for p in standings:
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
                                sig, _ = compute_deck_signature(all_cards)
                                p_id = (p.get("player") or p.get("name", "")).lower()
                                if p_id:
                                    player_to_sig[p_id] = sig
                                    
                        for m in pairings:
                            if not isinstance(m, dict): continue
                            p1 = m.get("player1")
                            p2 = m.get("player2")
                            if not p1 or not p2: continue
                            
                            if isinstance(p1, dict): p1 = p1.get("name") or p1.get("id")
                            if isinstance(p2, dict): p2 = p2.get("name") or p2.get("id")
                            
                            p1_sig = player_to_sig.get(p1.lower()) if p1 else None
                            p2_sig = player_to_sig.get(p2.lower()) if p2 else None
                            
                            if p1_sig and p2_sig:
                                winner = m.get("winner")
                                if isinstance(winner, dict): 
                                    winner = winner.get("name") or winner.get("id")
                                
                                winner_str = str(winner).lower() if winner is not None else None
                                p1_str = str(p1).lower()
                                p2_str = str(p2).lower()
                                
                                yield (date_str, p1_sig, p2_sig, winner_str, p1_str, p2_str)
                                
                    except Exception as e:
                        logger.error(f"Error processing tournament {t_id}: {e}")

def get_pair_key(sig1, sig2):
    """Returns a canonical key for a deck pair."""
    return tuple(sorted([sig1, sig2]))

def analyze_matchups():
    # Load Top Matchups Cache
    top_matchups = {}
    if os.path.exists(TOP_MATCHUPS_CACHE_FILE):
        with open(TOP_MATCHUPS_CACHE_FILE, "r") as f:
            raw_top_matchups = json.load(f)
            # Filter out mirror matches from cache in case they were already there
            for code, entries in raw_top_matchups.items():
                filtered_entries = [e for e in entries if e["pair"][0] != e["pair"][1]]
                if filtered_entries:
                    top_matchups[code] = filtered_entries
            # If cache is empty or incomplete, we need to scan
    # Also re-scan if we want to ensure 300+ match filter is applied across all periods
    needs_scan = False
    periods = get_set_periods() # This line was moved here from below the needs_scan block
    for p in periods:
        if p["code"] not in top_matchups:
            needs_scan = True
            break
        # Check if cached matches meet the 300 criteria (if we can verify it easily)
        # For now, let's just force a scan if we're changing the rules, 
        # but the logic below will already re-evaluate anyway if we don't return early.
    
    # Actually, let's force a scan this time to apply the 300 filter.
    needs_scan = True
            
    # Also need all-time stats for the selected pairs
    # Wait, the requirement says "tournament win rates はペアの選出期間に限らず、全期間を対象にして算出して下さい。"
    # This means I need to aggregate ALL pairings anyway to get the win rates for the top pairs.
    
    period_matchup_counts = defaultdict(Counter) # period_code -> pair_key -> count
    all_time_matchup_stats = defaultdict(lambda: {"wins": 0, "total": 0}) # pair_key -> {wins, total}
    
    logger.info("Scanning all tournament pairings...")
    for date_str, sig1, sig2, winner, p1_id, p2_id in get_all_pairings():
        pair_key = get_pair_key(sig1, sig2)
        
        # All time stats for p1 win rate in this specific pair
        # We store stats for the canonical pair: (sigA, sigB) where sigA < sigB
        # If the yielded sig1 is the first one in key, p1 is sigA.
        sorted_keys = sorted([sig1, sig2])
        canonical_sig1 = sorted_keys[0]
        
        all_time_matchup_stats[pair_key]["total"] += 1
        if winner:
            if winner == p1_id:
                if sig1 == canonical_sig1:
                    all_time_matchup_stats[pair_key]["wins"] += 1
            elif winner == p2_id:
                if sig2 == canonical_sig1:
                    all_time_matchup_stats[pair_key]["wins"] += 1
            else:
                # Tie
                all_time_matchup_stats[pair_key]["wins"] += 0.5
        else:
            # Tie assumed if no winner
            all_time_matchup_stats[pair_key]["wins"] += 0.5
            
        # Period counts
        for p in periods:
            if (not p["start"] or date_str >= p["start"]) and (not p["end"] or date_str <= p["end"]):
                period_matchup_counts[p["code"]][pair_key] += 1
                
    # Determine top 3 matchups per period (excluding mirror matches and < 300 total matches)
    top_matchups = {} # Reset to apply new filters
    for p in periods:
        code = p["code"]
        counts = period_matchup_counts[code]
        # Filter out mirror matches AND ensure total all-time matches >= 300
        valid_pairs = []
        for pair, count in counts.items():
            if pair[0] != pair[1] and all_time_matchup_stats[pair]["total"] >= 300:
                valid_pairs.append((pair, count))
        
        # Sort by count (period frequency) descending and take top 3
        valid_pairs.sort(key=lambda x: x[1], reverse=True)
        top_3 = valid_pairs[:3]
        
        if top_3:
            # Convert keys to list of strings for JSON
            top_matchups[code] = [{
                "pair": list(pair),
                "count": count
            } for pair, count in top_3]
            
    # Save Top Matchups Cache
    with open(TOP_MATCHUPS_CACHE_FILE, "w") as f:
        json.dump(top_matchups, f, indent=2)
        
    return periods, top_matchups, all_time_matchup_stats

def load_sim_cache():
    if os.path.exists(SIMULATION_CACHE_FILE):
        with open(SIMULATION_CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_sim_cache(cache):
    with open(SIMULATION_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def run_and_report():
    periods, top_matchups, all_time_stats = analyze_matchups()
    sim_cache = load_sim_cache()
    
    unique_pairs_to_simulate = set()
    for period_code in top_matchups:
        for entry in top_matchups[period_code]:
            pair = tuple(entry["pair"])
            unique_pairs_to_simulate.add(pair)
            
    results = []
    
    for pair in unique_pairs_to_simulate:
        sig1, sig2 = pair
        pair_key_str = f"{sig1}_{sig2}"
        
        # Check cache
        cached = sim_cache.get(pair_key_str, {"wins": 0, "total": 0})
        
        # Only simulate if we need more games?
        # The user said: "新たにシミュレーションを行った場合は、キャッシュと合計して結果を表示して、キャッシュを更新して下さい。"
        # This implies we can run it again and add to the totals.
        # Let's run 100 games if we don't have enough, or just run 100 more if asked?
        # For this script, let's ensure at least 100 games in total.
        
        current_total = cached.get("total", 0)
        needed = max(0, 1000 - current_total)
        
        if needed > 0:
            logger.info(f"Simulating {sig1} vs {sig2} for {needed} games (already have {current_total}, target 1000)...")
            print(f"[{len(results)+1}/{len(unique_pairs_to_simulate)}] Simulating {sig1} vs {sig2} (need {needed} more)...")
            try:
                deck1_path = convert_signature_to_deckgym(sig1)
                deck2_path = convert_signature_to_deckgym(sig2)
                
                # run_simulation returns win rate percentage of deck1
                win_rate = run_simulation(deck1_path, deck2_path, num_games=needed)
                
                new_wins = (win_rate / 100.0) * needed
                cached["wins"] = cached.get("wins", 0) + new_wins
                cached["total"] = cached.get("total", 0) + needed
                sim_cache[pair_key_str] = cached
                save_sim_cache(sim_cache)
            except Exception as e:
                logger.error(f"Simulation failed for {pair}: {e}")
                continue
                
    # Now build the table
    all_rows = []
    
    # Get deck names for display
    all_sigs_involved = set()
    for pair in unique_pairs_to_simulate:
        all_sigs_involved.update(pair)
    deck_details = get_deck_details_by_signature(list(all_sigs_involved))
    
    for p in periods:
        code = p["code"]
        p_matchups = top_matchups.get(code, [])
        for entry in p_matchups:
            sig1, sig2 = entry["pair"]
            pair_key = get_pair_key(sig1, sig2)
            pair_key_str = f"{sig1}_{sig2}"
            
            # Tournament Stats (p1 vs p2)
            stats = all_time_stats.get(pair_key, {"wins": 0, "total": 0})
            t_wins = stats["wins"]
            t_total = stats["total"]
            t_wr = (t_wins / t_total * 100) if t_total > 0 else 0
            
            # Simulation Stats
            s_cached = sim_cache.get(pair_key_str, {"wins": 0, "total": 0})
            s_wins = s_cached["wins"]
            s_total = s_cached["total"]
            s_wr = (s_wins / s_total * 100) if s_total > 0 else 0

            # Chi-squared test
            p_val = "-"
            if t_total > 0 and s_total > 0:
                # 2x2 contingency table: [[Tournament Wins, Tournament Losses], [Sim Wins, Sim Losses]]
                # Using max(0, ...) to ensure no negative counts due to tie handling (0.5 wins)
                table = [
                    [t_wins, max(0, t_total - t_wins)],
                    [s_wins, max(0, s_total - s_wins)]
                ]
                try:
                    chi2, p, dof, ex = chi2_contingency(table)
                    p_val = f"{p:.3f}"
                except Exception:
                    p_val = "Error"
            
            name1 = deck_details.get(sig1, {}).get("name", sig1)
            name2 = deck_details.get(sig2, {}).get("name", sig2)
            
            all_rows.append({
                "Period": p["name"],
                "Deck 1": f"{name1} ({sig1[:6]})",
                "Deck 2": f"{name2} ({sig2[:6]})",
                "Matches": entry["count"],
                "Total T-Matches": t_total,
                "T-WinRate %": f"{t_wr:.1f}%",
                "S-WinRate %": f"{s_wr:.1f}%",
                "Diff": f"{abs(t_wr - s_wr):.1f}%",
                "Chi2 p-value": p_val
            })
            
    df = pd.DataFrame(all_rows)
    print("\nComparison of Tournament vs Simulation Results (Top 3 Matchups per Period)")
    print(df.to_string(index=False))
    
    # Save the report to a file as well
    df.to_csv(os.path.join(CACHE_DIR, "matchup_comparison_report.csv"), index=False)
    logger.info(f"Report saved to {os.path.join(CACHE_DIR, 'matchup_comparison_report.csv')}")

if __name__ == "__main__":
    run_and_report()
