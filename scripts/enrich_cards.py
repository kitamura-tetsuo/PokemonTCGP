import json
import os
import csv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.getcwd(), "data")
CARDS_DIR = os.path.join(DATA_DIR, "cards")
ENRICHED_FILE = os.path.join(CARDS_DIR, "enriched_cards.json")
UNKNOWN_CSV = os.path.join(CARDS_DIR, "unknown_cards.csv")
TRANSLATIONS_FILE = os.path.join(DATA_DIR, "card_translations.json")

def _normalize_type(t):
    """Normalize various type names to a consistent set: Pokemon, Goods, Item, Stadium, Support."""
    if not t:
        return "Unknown"
    t = t.lower().strip()
    if t in ["pokemon", "pokemon (heuristic)"]:
        return "Pokemon"
    if t in ["goods", "item", "item (heuristic)"]:
        return "Goods"
    if t in ["tool", "item"]: # Fallback
        return "Item"
    if t in ["supporter", "support"]:
        return "Support"
    if t in ["stadium"]:
        return "Stadium"
    return t.capitalize()

def load_translations():
    if os.path.exists(TRANSLATIONS_FILE):
        try:
            with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading translations: {e}")
    return {}

def enrich_all_cards():
    logger.info("Starting card enrichment process...")
    
    # 1. Load Translations
    translations = load_translations()
    
    # 2. Load CSV Overrides
    csv_overrides = {}
    if os.path.exists(UNKNOWN_CSV):
        try:
            with open(UNKNOWN_CSV, "r", encoding="utf-8") as f:
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
        except Exception as e:
            logger.error(f"Error loading unknown_cards.csv: {e}")

    # 3. Load Raw Cards
    cards_map = {}
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

    # 4. Process and Enrich
    enriched_db = {}
    for (c_set, c_num), item in cards_map.items():
        # Type Logic (replicated from data.py)
        c_type = csv_overrides.get((c_set, c_num))
        if not c_type:
            c_type = item.get("type")
            if c_type:
                c_type = _normalize_type(c_type)
        
        if not c_type or c_type == "Unknown":
            img = item.get("image", "")
            if img.startswith("cPK"):
                c_type = "Pokemon"
            elif img.startswith("cTR"):
                c_type = "Goods"
        
        c_name = item.get("name")
        name_ja = translations.get(c_name, c_name) if c_name else ""

        enriched_db[f"{c_set}_{c_num}"] = {
            "name": c_name,
            "set": c_set,
            "number": c_num,
            "type": c_type or "Unknown",
            "image": item.get("image"),
            "name_ja": name_ja
        }

    # 5. Save Enriched DB
    try:
        os.makedirs(os.path.dirname(ENRICHED_FILE), exist_ok=True)
        with open(ENRICHED_FILE, "w", encoding="utf-8") as f:
            json.dump(enriched_db, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully saved {len(enriched_db)} enriched cards to {ENRICHED_FILE}")
    except Exception as e:
        logger.error(f"Error saving enriched cards: {e}")

if __name__ == "__main__":
    enrich_all_cards()
