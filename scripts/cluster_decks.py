
import json
import os
import argparse
import logging
import time
import numpy as np
from scipy.sparse import csr_matrix, lil_matrix, diags
from scipy.sparse.csgraph import connected_components
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Constants
CACHE_FILE = "data/cache/daily_exact_stats.json"

# Globals for workers
worker_context = {}

def get_binary_features_and_buckets(signatures):
    """
    Convert signatures to sparse binary feature matrices and bucket by Pokemon Sets.
    """
    logger.info("Building sparse feature space and buckets...")
    
    all_card_keys = set()
    sigs = list(signatures.keys())
    
    # 1. Collect keys
    for sig in sigs:
        for c in signatures[sig]["cards"]:
            all_card_keys.add((c["name"], c.get("type", "Unknown")))
            
    sorted_keys = sorted(list(all_card_keys))
    key_to_idx = {k: i for i, k in enumerate(sorted_keys)}
    n_features = len(sorted_keys)
    n_decks = len(sigs)
    
    logger.info(f"Feature space: {n_decks} decks x {n_features} unique cards")
    
    # Identify Pokemon indices and Weights
    base_weights = np.zeros(n_features, dtype=np.float32)
    feature_weights = np.zeros(2*n_features, dtype=np.float32)
    
    for i, (name, c_type) in enumerate(sorted_keys):
        if c_type == "Pokemon":
            w = 0.5
        else:
            w = 0.125
            
        base_weights[i] = w
        feature_weights[2*i] = 2 * w
        feature_weights[2*i+1] = 2 * w

    # Structures
    F_rows, F_cols, F_data = [], [], []
    X1_rows, X1_cols, X1_data = [], [], []
    X2_rows, X2_cols, X2_data = [], [], []
    
    # Bucketing
    buckets = defaultdict(list)
    bucket_bitmasks = [] 
    unique_buckets = {} 
    
    for row_idx, sig in enumerate(sigs):
        cards = signatures[sig]["cards"]
        pokemon_set = set()
        
        for c in cards:
            key = (c["name"], c.get("type", "Unknown"))
            if key in key_to_idx:
                k = key_to_idx[key]
                count = c.get("count", 1)
                
                if key[1] == "Pokemon":
                    pokemon_set.add(k)

                if count >= 1:
                    F_rows.append(row_idx)
                    F_cols.append(2*k)
                    F_data.append(1)
                    if count == 1:
                        X1_rows.append(row_idx)
                        X1_cols.append(k)
                        X1_data.append(1)
                
                if count >= 2:
                    F_rows.append(row_idx)
                    F_cols.append(2*k + 1)
                    F_data.append(1)
                    X2_rows.append(row_idx)
                    X2_cols.append(k)
                    X2_data.append(1)
        
        p_frozen = frozenset(pokemon_set)
        if p_frozen not in unique_buckets:
            mask = 0
            for p_idx in p_frozen:
                mask |= (1 << p_idx)
            
            bid = len(unique_buckets)
            unique_buckets[p_frozen] = bid
            bucket_bitmasks.append(mask)
            
        bid = unique_buckets[p_frozen]
        buckets[bid].append(row_idx)
                    
    # Create matrices
    F_binary = csr_matrix((F_data, (F_rows, F_cols)), shape=(n_decks, 2*n_features), dtype=np.float32)
    X1_binary = csr_matrix((X1_data, (X1_rows, X1_cols)), shape=(n_decks, n_features), dtype=np.float32)
    X2_binary = csr_matrix((X2_data, (X2_rows, X2_cols)), shape=(n_decks, n_features), dtype=np.float32)
    
    return F_binary, feature_weights, X1_binary, X2_binary, base_weights, sigs, buckets, bucket_bitmasks

def init_worker_full(masks, F_bin, F_w, X1, X2, base_w, norms):
    worker_context['masks'] = masks
    worker_context['F_bin'] = F_bin
    worker_context['F_weighted'] = F_bin @ diags(F_w)
    worker_context['X1_weighted'] = X1 @ diags(base_w)
    worker_context['X2_weighted'] = (X2 @ diags(base_w))
    worker_context['X1'] = X1
    worker_context['X2'] = X2
    worker_context['norms'] = norms

def find_bucket_neighbors_worker(args):
    """Check hamming distance for a range of buckets."""
    start_idx, end_idx = args
    masks = worker_context['masks']
    n_masks = len(masks)
    results = []
    
    for i in range(start_idx, end_idx):
        m1 = masks[i]
        results.append((i, i)) # Self
        
        for j in range(i + 1, n_masks):
            m2 = masks[j]
            xor_val = m1 ^ m2
            
            if xor_val == 0:
                results.append((i, j))
                continue
                
            y = xor_val & (xor_val - 1)
            if y == 0: 
                results.append((i, j))
                continue
                
            z = y & (y - 1)
            if z == 0: 
                results.append((i, j))
                
    return results

def calculate_dist_worker(args):
    """Calculate distance for a chunk of pairs."""
    rows, cols, threshold = args
    
    F_bin = worker_context['F_bin']
    F_weighted = worker_context['F_weighted']
    X1_weighted = worker_context['X1_weighted']
    X2_weighted = worker_context['X2_weighted']
    X1 = worker_context['X1']
    X2 = worker_context['X2']
    norms = worker_context['norms']
    
    # 1. Intersection
    m1 = F_weighted[rows]
    m2 = F_bin[cols]
    inters = m1.multiply(m2).sum(axis=1).A1
    
    # 2. Correction
    x1_r = X1_weighted[rows]
    x2_c = X2[cols]
    x2_r = X2_weighted[rows]
    x1_c = X1[cols]
    
    corr1 = x1_r.multiply(x2_c).sum(axis=1).A1
    corr2 = x2_r.multiply(x1_c).sum(axis=1).A1
    correction = corr1 + corr2
    
    # 3. Distance
    n_r = norms[rows]
    n_c = norms[cols]
    dists = n_r + n_c - 2 * inters - correction
    
    match_mask = dists <= (threshold + 1e-6)
    
    if np.any(match_mask):
        idx = np.where(match_mask)[0]
        return np.array(rows[idx]), np.array(cols[idx]) # Return as arrays
    return None, None

def cluster_decks_bucketed_parallel(signatures, threshold=1.0):
    start_time = time.time()
    F_bin, F_w, X1, X2, base_w, sigs, buckets, bucket_bitmasks = get_binary_features_and_buckets(signatures)
    n_decks = len(sigs)
    n_buckets = len(buckets)
    
    logger.info(f"Grouped {n_decks} decks into {n_buckets} unique Pokemon Sets.")
    
    logger.info("Computing norms...")
    norms = F_bin.dot(F_w)
    
    n_workers = max(1, os.cpu_count())
    logger.info(f"Using {n_workers} workers.")
    
    # Initialize Pool with all data
    # Note: sharing F_bin etc with workers via simple inheritance/global?
    # Or initializer.
    # Initializer is better.
    
    logger.info("Identifying bucket neighbors...")
    check_start = time.time()
    
    chunk_size = (n_buckets + n_workers - 1) // n_workers
    ranges = []
    for i in range(0, n_buckets, chunk_size):
        ranges.append((i, min(i + chunk_size, n_buckets)))
        
    bucket_adj = defaultdict(list)
    
    # We create executor OUTSIDE to reuse it?
    # Reusing keeps initialized data alive.
    
    with ProcessPoolExecutor(max_workers=n_workers, initializer=init_worker_full, 
                            initargs=(bucket_bitmasks, F_bin, F_w, X1, X2, base_w, norms)) as executor:
        
        # Step 1: Buckets
        results = executor.map(find_bucket_neighbors_worker, ranges)
        for sub_res in results:
            for b1, b2 in sub_res:
                bucket_adj[b1].append(b2)
                if b1 != b2:
                    bucket_adj[b2].append(b1)
                    
        elapsed_buckets = time.time() - check_start
        logger.info(f"Bucket neighbor search took {elapsed_buckets:.2f}s")
        
        logger.info("Generating candidate deck pairs...")
        cand_pairs_accum = []
        for b1, neighbors in bucket_adj.items():
            decks1 = buckets[b1]
            for b2 in neighbors:
                if b2 < b1: continue 
                decks2 = buckets[b2]
                if b1 == b2:
                    n = len(decks1)
                    for i in range(n):
                        for j in range(i+1, n):
                            if decks1[i] < decks1[j]: 
                                 cand_pairs_accum.append((decks1[i], decks1[j]))
                            else:
                                 cand_pairs_accum.append((decks1[j], decks1[i]))
                else:
                    for d1 in decks1:
                        for d2 in decks2:
                            if d1 < d2:
                                cand_pairs_accum.append((d1, d2))
                            else:
                                cand_pairs_accum.append((d2, d1))
                                
        n_candidates = len(cand_pairs_accum)
        logger.info(f"Checking {n_candidates} candidate pairs...")
        
        adj_matrix = lil_matrix((n_decks, n_decks), dtype=np.bool_)
        
        if n_candidates > 0:
            logger.info("Computing distances via pool...")
            
            cand_pairs_arr = np.array(cand_pairs_accum)
            all_rows = cand_pairs_arr[:, 0]
            all_cols = cand_pairs_arr[:, 1]
            
            dist_chunk_size = 50000
            dist_chunks = []
            for start in range(0, n_candidates, dist_chunk_size):
                end = min(start + dist_chunk_size, n_candidates)
                dist_chunks.append((all_rows[start:end], all_cols[start:end], threshold))
                
            dist_results = executor.map(calculate_dist_worker, dist_chunks)
            
            for r_rows, r_cols in dist_results:
                if r_rows is not None and len(r_rows) > 0:
                    # Fix writeable issue
                    r_rows = np.array(r_rows)
                    r_cols = np.array(r_cols)
                    adj_matrix[r_rows, r_cols] = 1
                    adj_matrix[r_cols, r_rows] = 1

    elapsed_calc = time.time() - start_time
    logger.info(f"Total Calculation took {elapsed_calc:.2f}s")
    
    logger.info("Finding connected components...")
    n_components, labels = connected_components(csgraph=adj_matrix, directed=False)
    
    logger.info(f"Found {n_components} clusters.")
    
    clusters = [[] for _ in range(n_components)]
    for idx, label in enumerate(labels):
        clusters[label].append(sigs[idx])
        
    return clusters

def main():
    parser = argparse.ArgumentParser(description="Cluster Pokemon TCG Pocket decks based on distance rules.")
    parser.add_argument("--threshold", type=float, default=1.0, help="Distance threshold for clustering (default: 1.0)")
    parser.add_argument("--output", type=str, default="data/cache/clusters.json", help="Output JSON file")
    args = parser.parse_args()

    if not os.path.exists(CACHE_FILE):
        logger.error(f"Cache file not found: {CACHE_FILE}")
        return

    logger.info(f"Loading {CACHE_FILE}...")
    with open(CACHE_FILE, "r") as f:
        data = json.load(f)

    signatures = data.get("signatures", {})
    if not signatures:
        logger.error("No signatures found in cache.")
        return

    start_total = time.time()
    clusters = cluster_decks_bucketed_parallel(signatures, threshold=args.threshold)
    
    logger.info(f"Found {len(clusters)} clusters from {len(signatures)} decks ({len(signatures)-len(clusters)} merged).")

    output_data = []
    
    logger.info("Processing cluster representatives...")
    sig_stats = {s: signatures[s].get("stats", {}).get("players", 0) for s in signatures}
    sig_names = {s: signatures[s].get("name", "Unknown") for s in signatures}
    
    for i, cluster_sigs in enumerate(clusters):
        cluster_sigs.sort(key=lambda s: sig_stats.get(s, 0), reverse=True)
        rep_sig = cluster_sigs[0]
        rep_name = sig_names.get(rep_sig, "Unknown")
        
        output_data.append({
            "id": i,
            "representative_name": rep_name,
            "representative_sig": rep_sig,
            "signatures": cluster_sigs,
            "count": len(cluster_sigs)
        })

    def get_cluster_players(c):
        return sum(sig_stats.get(s, 0) for s in c["signatures"])
    
    output_data.sort(key=get_cluster_players, reverse=True)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    temp_output = args.output + ".tmp"
    with open(temp_output, "w") as f:
        json.dump(output_data, f, indent=2)
    os.replace(temp_output, args.output)
    
    total_elapsed = time.time() - start_total
    logger.info(f"Clusters saved to {args.output}")
    logger.info(f"Total execution time: {total_elapsed:.2f}s")
    
    print("\nTop Clusters:")
    for i, c in enumerate(output_data[:10]):
        total_players = get_cluster_players(c)
        print(f"{i+1}. {c['representative_name']} ({c['representative_sig']}): {c['count']} variants, {total_players} players")

if __name__ == "__main__":
    main()
