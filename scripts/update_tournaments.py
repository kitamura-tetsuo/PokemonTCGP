
import requests
import time
import json
import os
import argparse
from datetime import datetime

# Constants
API_BASE_URL = "https://play.limitlesstcg.com/api"
RATE_LIMIT_DELAY = 1.0  # seconds between requests
DATA_DIR = "data/tournaments"
CARD_DB_URLS = {
    "cards.json": "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.json",
    "cards.extra.json": "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.extra.json",
    "sets.json": "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/sets.json"
}

def fetch_json(endpoint, params=None):
    """Fetch JSON from API with rate limiting."""
    url = f"{API_BASE_URL}{endpoint}"
    print(f"Fetching {url}...")
    try:
        response = requests.get(url, params=params)
        time.sleep(RATE_LIMIT_DELAY)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            print(f"⚠️ Rate limited! Waiting 10 seconds...")
            time.sleep(10)
            return fetch_json(endpoint, params)
        else:
            print(f"❌ API Error {response.status_code} for {url}")
            return None
    except Exception as e:
        print(f"❌ Exception fetching {url}: {e}")
        return None

def get_recent_tournaments_api(limit=50, page=1):
    """Get recent POCKET tournaments from API."""
    params = {
        "game": "POCKET",
        "limit": limit,
        "page": page
    }
    return fetch_json("/tournaments", params=params) or []

def fetch_tournament_full_data(tournament_id):
    """Fetch details, standings, and pairings."""
    details = fetch_json(f"/tournaments/{tournament_id}/details")
    if not details:
        return None, None, None
        
    standings = fetch_json(f"/tournaments/{tournament_id}/standings")
    pairings = fetch_json(f"/tournaments/{tournament_id}/pairings")
    
    return details, standings, pairings

def get_date_folder_path(date_str):
    """Convert ISO date string to YYYY/MM/DD folder path."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
    except ValueError:
        now = datetime.now()
        return f"{now.year}/{now.month:02d}/{now.day:02d}"

def update_card_database():
    """Fetch card database from GitHub."""
    print("Updating card database from GitHub...")
    save_dir = os.path.join("data", "cards")
    os.makedirs(save_dir, exist_ok=True)
    
    for filename, url in CARD_DB_URLS.items():
        print(f"Fetching {filename}...")
        try:
            response = requests.get(url)
            if response.status_code == 200:
                with open(os.path.join(save_dir, filename), 'w') as f:
                    # Parse and re-dump to ensure it's valid JSON and pretty-print if desired
                    data = response.json()
                    json.dump(data, f, indent=2)
                print(f"✅ Saved {filename}")
            else:
                print(f"❌ Failed to fetch {filename}: {response.status_code}")
        except Exception as e:
            print(f"❌ Exception fetching {filename}: {e}")

def update_tournament_cache():
    parser = argparse.ArgumentParser(description='Update tournament cache.')
    parser.add_argument('--init', action='store_true', help='Initial run: fetch history')
    args = parser.parse_args()
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    page = 1
    limit = 50
    overlap_buffer = 1
    stop_fetching = False
    
    total_new = 0
    
    print(f"Starting update (Init: {args.init})...")
    
    # Step 1: Update Card Database
    update_card_database()
    
    while not stop_fetching:
        print(f"Fetching page {page}...")
        recent_tournaments = get_recent_tournaments_api(limit=limit, page=page)
        
        if not recent_tournaments:
            print("No more tournaments found.")
            break
            
        print(f"Page {page}: Found {len(recent_tournaments)} tournaments on API")
        
        new_tournaments_in_page = []
        page_has_existing = False
        
        for t_info in recent_tournaments:
            date_folder = get_date_folder_path(t_info['date'])
            t_id = t_info['id']
            
            # Check if exists
            target_dir = os.path.join(DATA_DIR, date_folder, t_id)
            if os.path.exists(os.path.join(target_dir, "details.json")):
                page_has_existing = True
            else:
                new_tournaments_in_page.append(t_info)
        
        print(f"Page {page}: {len(new_tournaments_in_page)} new to process")
        
        for t_info in new_tournaments_in_page:
            t_id = t_info['id']
            print(f"Processing {t_info['name']} ({t_id})...")
            
            details, standings, pairings = fetch_tournament_full_data(t_id)
            
            if details and standings:
                date_folder = get_date_folder_path(details['date'])
                save_dir = os.path.join(DATA_DIR, date_folder, t_id)
                os.makedirs(save_dir, exist_ok=True)
                
                with open(os.path.join(save_dir, "details.json"), 'w') as f:
                    json.dump(details, f, indent=2)
                with open(os.path.join(save_dir, "standings.json"), 'w') as f:
                    json.dump(standings, f, indent=2)
                if pairings:
                    with open(os.path.join(save_dir, "pairings.json"), 'w') as f:
                        json.dump(pairings, f, indent=2)
                        
                total_new += 1
                print(f"✅ Saved {t_id}")
            else:
                print(f"❌ Failed to fetch {t_id}")
                
        if not args.init:
            if page_has_existing:
                if overlap_buffer > 0:
                    print(f"Found existing data. Buffer remaining: {overlap_buffer}")
                    overlap_buffer -= 1
                else:
                    print("Reached overlapping data. Stopping.")
                    stop_fetching = True
        
        page += 1
        
    print(f"Update complete. Processed {total_new} new tournaments.")

if __name__ == "__main__":
    update_tournament_cache()
