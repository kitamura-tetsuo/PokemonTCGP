
import sqlite3
import json
import os
import logging
import pandas as pd
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

CACHE_FILE = "data/cache/daily_exact_stats.pkl.gz"
CLUSTERS_FILE = "data/cache/clusters.json"
DB_FILE = "data/cache/stats.db"

def init_db(conn):
    cursor = conn.cursor()
    
    # Daily stats for both signatures and clusters
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_stats (
        date TEXT,
        identifier TEXT,
        is_cluster INTEGER,
        wins INTEGER,
        losses INTEGER,
        ties INTEGER,
        players INTEGER,
        matches INTEGER,
        PRIMARY KEY (date, identifier)
    )
    ''')
    
    # Metagame totals per day
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS metagame_totals (
        date TEXT PRIMARY KEY,
        total_players INTEGER,
        total_matches INTEGER
    )
    ''')
    
    # Signature details
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS signatures (
        sig TEXT PRIMARY KEY,
        name TEXT,
        cards TEXT,
        stats TEXT
    )
    ''')
    
    # Cluster details
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS clusters (
        cluster_id TEXT PRIMARY KEY,
        name TEXT,
        representative_sig TEXT,
        signatures TEXT,
        cards TEXT,
        stats TEXT
    )
    ''')
    
    # Indexes for speed
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_stats_id ON daily_stats(identifier)')
    
    conn.commit()

def populate_db():
    if not os.path.exists(CACHE_FILE):
        logger.error(f"Cache file not found: {CACHE_FILE}")
        return

    logger.info(f"Loading {CACHE_FILE}...")
    data = pd.read_pickle(CACHE_FILE)
    cache = data.get("dates", {})
    signatures = data.get("signatures", {})
    
    clusters = []
    if os.path.exists(CLUSTERS_FILE):
        logger.info(f"Loading {CLUSTERS_FILE}...")
        with open(CLUSTERS_FILE, "r") as f:
            clusters = json.load(f)

    try:
        conn = sqlite3.connect(DB_FILE)
        init_db(conn)
    except sqlite3.DatabaseError as e:
        logger.warning(f"Database file {DB_FILE} is corrupted or not a database ({e}). Re-creating it...")
        try:
            conn.close()
        except Exception:
            pass
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        conn = sqlite3.connect(DB_FILE)
        init_db(conn)

    cursor = conn.cursor()
    
    # Clear existing data for a fresh start (or we could do incremental, but full is safer for now)
    cursor.execute('DELETE FROM daily_stats')
    cursor.execute('DELETE FROM metagame_totals')
    cursor.execute('DELETE FROM signatures')
    cursor.execute('DELETE FROM clusters')

    # 1. Populate signatures
    logger.info("Populating signatures table...")
    sig_data = []
    for sig, info in signatures.items():
        sig_data.append((
            sig,
            info.get("name", "Unknown"),
            json.dumps(info.get("cards", [])),
            json.dumps(info.get("stats", {}))
        ))
    cursor.executemany('INSERT INTO signatures VALUES (?, ?, ?, ?)', sig_data)

    # 2. Populate clusters
    logger.info("Populating clusters table...")
    cluster_data = []
    for c in clusters:
        # Calculate cluster-wide stats
        c_stats = {"wins": 0, "losses": 0, "ties": 0, "players": 0}
        for sig in c["signatures"]:
            s = signatures.get(sig, {}).get("stats", {})
            for k in c_stats:
                c_stats[k] += s.get(k, 0)
        
        rep_sig = c["representative_sig"]
        rep_cards = signatures.get(rep_sig, {}).get("cards", [])
        
        cluster_data.append((
            str(c["id"]),
            c["representative_name"],
            rep_sig,
            json.dumps(c["signatures"]),
            json.dumps(rep_cards),
            json.dumps(c_stats)
        ))
    cursor.executemany('INSERT INTO clusters VALUES (?, ?, ?, ?, ?, ?)', cluster_data)

    # 3. Populate daily_stats (Signatures) and metagame_totals
    logger.info("Populating daily_stats and metagame_totals...")
    
    # First, aggregate metagame totals and daily signature stats
    # We use a dictionary to accumulate because one signature might appear in multiple tournaments on the same day
    # Actually _scan_and_aggregate already handles this in the signatures['appearances']? 
    # No, cache['dates'] has it per tournament.
    
    daily_sig_stats = {} # (date, sig) -> {w, l, t, p, m}
    daily_totals = {} # date -> {p, m}
    
    for date_str, day_entry in cache.items():
        day_p = 0
        day_m = 0
        
        if "tournaments" in day_entry:
            for t_id, t_data in day_entry["tournaments"].items():
                # We count all decks in metagame total
                t_decks = t_data.get("decks", {})
                day_p += sum(t_decks.values())
                # For matches, we'd need to sum player records, but we don't have it easily here
                # Let's derive it from appearances later or just skip matches in totals if not needed
        elif "decks" in day_entry:
            day_p += sum(day_entry["decks"].values())
        
        daily_totals[date_str] = {"p": day_p, "m": 0}

    # Better way: iterate through signature appearances
    for sig, info in signatures.items():
        for app in info.get("appearances", []):
            date_str = app.get("date")
            if not date_str: continue
            
            rec = app.get("record", {})
            w, l, t = rec.get("wins", 0), rec.get("losses", 0), rec.get("ties", 0)
            m = w + l + t
            
            key = (date_str, sig)
            if key not in daily_sig_stats:
                daily_sig_stats[key] = {"w": 0, "l": 0, "t": 0, "p": 0, "m": 0}
            
            daily_sig_stats[key]["w"] += w
            daily_sig_stats[key]["l"] += l
            daily_sig_stats[key]["t"] += t
            daily_sig_stats[key]["p"] += 1
            daily_sig_stats[key]["m"] += m
            
            # Update daily totals match count
            if date_str in daily_totals:
                daily_totals[date_str]["m"] += m

    # 4. Populate daily_stats (Clusters)
    logger.info("Aggregating daily cluster stats...")
    daily_cluster_stats = {} # (date, cluster_id) -> {w, l, t, p, m}
    
    sig_to_cluster = {}
    for c in clusters:
        cid = str(c["id"])
        for sig in c["signatures"]:
            sig_to_cluster[sig] = cid
            
    for (date_str, sig), stats in daily_sig_stats.items():
        cid = sig_to_cluster.get(sig)
        if cid:
            key = (date_str, cid)
            if key not in daily_cluster_stats:
                daily_cluster_stats[key] = {"w": 0, "l": 0, "t": 0, "p": 0, "m": 0}
            
            for k in stats:
                daily_cluster_stats[key][k] += stats[k]

    # Insert into DB
    logger.info("Inserting daily records...")
    
    # Metagame Totals
    totals_rows = [(d, s["p"], s["m"]) for d, s in daily_totals.items()]
    cursor.executemany('INSERT INTO metagame_totals VALUES (?, ?, ?)', totals_rows)
    
    # Signature daily stats
    sig_daily_rows = [
        (date, sig, 0, s["w"], s["l"], s["t"], s["p"], s["m"])
        for (date, sig), s in daily_sig_stats.items()
    ]
    cursor.executemany('INSERT INTO daily_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?)', sig_daily_rows)
    
    # Cluster daily stats
    cluster_daily_rows = [
        (date, cid, 1, s["w"], s["l"], s["t"], s["p"], s["m"])
        for (date, cid), s in daily_cluster_stats.items()
    ]
    cursor.executemany('INSERT INTO daily_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?)', cluster_daily_rows)

    conn.commit()
    conn.close()
    logger.info(f"✅ SQLite database populated at {DB_FILE}")

if __name__ == "__main__":
    populate_db()
