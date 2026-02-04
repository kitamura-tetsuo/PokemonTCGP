import json
import os
import re

CARDS_DIR = os.path.join(os.getcwd(), "data", "cards")
ENRICHED_CARDS_FILE = os.path.join(CARDS_DIR, "enriched_cards.json")

def normalize_type(t):
    if not t:
        return "Unknown"
    t = t.lower().strip()
    if "pokemon" in t:
        return "Pokemon"
    if "item" in t or "goods" in t:
        return "Item"
    if "supporter" in t or "support" in t:
        return "Support"
    if "stadium" in t:
        return "Stadium"
    return t.capitalize()

def cleanup():
    if not os.path.exists(ENRICHED_CARDS_FILE):
        print(f"File not found: {ENRICHED_CARDS_FILE}")
        return

    with open(ENRICHED_CARDS_FILE, "r") as f:
        data = json.load(f)

    print(f"Original card count: {len(data)}")

    # Group cards by (name, set, normalized_type)
    groups = {}
    for key, info in data.items():
        name = info.get("name")
        c_set = info.get("set")
        c_type = normalize_type(info.get("type"))
        
        if not name or not c_set:
            continue
            
        fingerprint = (name, c_set, c_type)
        if fingerprint not in groups:
            groups[fingerprint] = []
        groups[fingerprint].append(key)

    new_data = {}
    removed_count = 0
    a4b_count = 0

    for fingerprint, keys in groups.items():
        name, c_set, c_type = fingerprint
        
        # Explicitly skip A4b set
        if c_set == "A4b":
            a4b_count += len(keys)
            continue

        # Sort keys to find the one with the smallest number
        # IDs are usually in the format SET_NUMBER (e.g., A1_1)
        # We want to sort by the numeric value of the number after the underscore
        def get_numeric_suffix(k):
            match = re.search(r'_(\d+)$', k)
            if match:
                return int(match.group(1))
            return 9999 # Fallback
            
        sorted_keys = sorted(keys, key=get_numeric_suffix)
        canonical_key = sorted_keys[0]
        
        new_data[canonical_key] = data[canonical_key]
        removed_count += (len(keys) - 1)

    print(f"Removed {removed_count} duplicate variants within sets.")
    print(f"Removed {a4b_count} cards from A4b reprint set.")
    print(f"New card count: {len(new_data)}")

    # Save back to file
    with open(ENRICHED_CARDS_FILE, "w") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)
    
    print("Cleanup complete.")

if __name__ == "__main__":
    cleanup()
