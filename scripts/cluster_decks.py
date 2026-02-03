
import json
import os
import argparse
from collections import Counter
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Constants
CACHE_FILE = "data/cache/daily_exact_stats.json"

def calculate_distance(deck1_cards, deck2_cards):
    """
    Calculate the distance between two decks based on user-defined rules.
    deck_cards is a list of dicts: {"name": str, "type": str, "count": int}
    """
    # Convert to maps for easy comparison
    # Key by (name, type) to be safe, though name is usually enough
    def to_map(cards):
        m = {}
        for c in cards:
            key = (c.get("name"), c.get("type", "Unknown"))
            m[key] = m.get(key, 0) + c.get("count", 1)
        return m

    m1 = to_map(deck1_cards)
    m2 = to_map(deck2_cards)

    all_keys = set(m1.keys()) | set(m2.keys())
    total_dist = 0.0

    for key in all_keys:
        name, c_type = key
        count1 = m1.get(key, 0)
        count2 = m2.get(key, 0)
        
        is_pokemon = (c_type == "Pokemon")
        
        if count1 > 0 and count2 > 0:
            # Same card, different counts
            diff = abs(count1 - count2)
            if is_pokemon:
                total_dist += diff * 0.5
            else:
                total_dist += diff * 0.125
        else:
            # Card unique to one deck
            count = max(count1, count2)
            if is_pokemon:
                total_dist += count * 1.0
            else:
                total_dist += count * 0.25
                
    return total_dist

def cluster_decks(signatures, threshold=1.0):
    """
    Cluster decks based on distance threshold using connected components.
    signatures: dict from CACHE_FILE["signatures"]
    """
    sigs = list(signatures.keys())
    n = len(sigs)
    
    # Adjacency list for connected components
    adj = {sig: [] for sig in sigs}
    
    logger.info(f"Calculating distances for {n} decks...")
    
    # This is O(N^2), which is fine for a few hundred/thousand decks
    # If N is very large, we might need a more optimized approach
    for i in range(n):
        for j in range(i + 1, n):
            sig1 = sigs[i]
            sig2 = sigs[j]
            
            dist = calculate_distance(signatures[sig1]["cards"], signatures[sig2]["cards"])
            
            if dist <= threshold:
                adj[sig1].append(sig2)
                adj[sig2].append(sig1)
                
    # Find connected components (BFS/DFS)
    visited = set()
    clusters = []
    
    for sig in sigs:
        if sig not in visited:
            # Start a new component
            component = []
            stack = [sig]
            visited.add(sig)
            
            while stack:
                curr = stack.pop()
                component.append(curr)
                
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
            
            clusters.append(component)
            
    return clusters

def main():
    parser = argparse.ArgumentParser(description="Cluster Pokemon TCG Pocket decks based on distance rules.")
    parser.add_argument("--threshold", type=float, default=1.0, help="Distance threshold for clustering (default: 1.0)")
    parser.add_argument("--output", type=str, default="data/cache/clusters.json", help="Output JSON file")
    args = parser.parse_args()

    if not os.path.exists(CACHE_FILE):
        logger.error(f"Cache file not found: {CACHE_FILE}")
        return

    with open(CACHE_FILE, "r") as f:
        data = json.load(f)

    signatures = data.get("signatures", {})
    if not signatures:
        logger.error("No signatures found in cache.")
        return

    clusters = cluster_decks(signatures, threshold=args.threshold)
    
    logger.info(f"Found {len(clusters)} clusters from {len(signatures)} decks.")

    # Prepare output: cluster -> {representative_name, signatures}
    output_data = []
    for i, cluster_sigs in enumerate(clusters):
        # Sort cluster by popularity (number of players) to find representative name
        cluster_sigs.sort(key=lambda s: signatures[s].get("stats", {}).get("players", 0), reverse=True)
        rep_sig = cluster_sigs[0]
        rep_name = signatures[rep_sig].get("name", "Unknown")
        
        output_data.append({
            "id": i,
            "representative_name": rep_name,
            "representative_sig": rep_sig,
            "signatures": cluster_sigs,
            "count": len(cluster_sigs)
        })

    # Sort clusters by total player count
    def get_cluster_players(c):
        return sum(signatures[s].get("stats", {}).get("players", 0) for s in c["signatures"])
    
    output_data.sort(key=get_cluster_players, reverse=True)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)
    
    logger.info(f"Clusters saved to {args.output}")

    # Print top clusters
    print("\nTop Clusters:")
    for i, c in enumerate(output_data[:10]):
        total_players = get_cluster_players(c)
        print(f"{i+1}. {c['representative_name']} ({c['representative_sig']}): {c['count']} variants, {total_players} players")

if __name__ == "__main__":
    main()
