import json
import os
import csv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.getcwd(), "data")
CARDS_DIR = os.path.join(DATA_DIR, "cards")
SETS_FILE = os.path.join(CARDS_DIR, "sets.json")
UNKNOWN_SETS_CSV = os.path.join(CARDS_DIR, "unknown_sets.csv")
ENRICHED_SETS_FILE = os.path.join(CARDS_DIR, "enriched_sets.json")

def enrich_sets():
    logger.info("Starting set enrichment process...")
    
    # 1. Load Raw Sets
    if not os.path.exists(SETS_FILE):
        logger.error(f"Source file {SETS_FILE} not found.")
        return

    try:
        with open(SETS_FILE, "r") as f:
            raw_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading {SETS_FILE}: {e}")
        return

    # Flatten the sets from their series groups
    all_sets = []
    for series in raw_data.values():
        for s in series:
            if "PROMO" not in s.get("code", ""):
                all_sets.append(s)

    # 2. Load CSV Overrides
    csv_overrides = {}
    if os.path.exists(UNKNOWN_SETS_CSV):
        try:
            with open(UNKNOWN_SETS_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = row.get("code")
                    name_ja = row.get("name_ja")
                    if code and name_ja:
                        csv_overrides[code] = name_ja.strip()
        except Exception as e:
            logger.error(f"Error loading {UNKNOWN_SETS_CSV}: {e}")

    # 3. Process and Enrich
    enriched_sets = []
    for s in all_sets:
        code = s.get("code")
        # Extract English name
        name_en = s.get("name", {}).get("en", code)
        
        # Determine Japanese name
        # Priority: 1. CSV Override, 2. Field in sets.json, 3. English name fallback
        name_ja = csv_overrides.get(code)
        if not name_ja:
            name_ja = s.get("name", {}).get("ja")
        
        if not name_ja:
            name_ja = name_en

        enriched_sets.append({
            "code": code,
            "releaseDate": s.get("releaseDate"),
            "name_en": name_en,
            "name_ja": name_ja
        })

    # Sort by release date (newest first for the UI, but here we can just save)
    enriched_sets.sort(key=lambda x: x.get("releaseDate", "9999-99-99"), reverse=True)

    # 4. Save Enriched Sets
    try:
        os.makedirs(os.path.dirname(ENRICHED_SETS_FILE), exist_ok=True)
        with open(ENRICHED_SETS_FILE, "w", encoding="utf-8") as f:
            json.dump(enriched_sets, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully saved {len(enriched_sets)} enriched sets to {ENRICHED_SETS_FILE}")
    except Exception as e:
        logger.error(f"Error saving enriched sets: {e}")

if __name__ == "__main__":
    enrich_sets()
