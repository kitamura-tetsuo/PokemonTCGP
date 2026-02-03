import os
import csv
import sys
import json

# Add project root to path to import src
sys.path.append(os.getcwd())

# We will read JSONs directly to see the RAW type before heuristic
DATA_DIR = os.path.join(os.getcwd(), "data")
CARDS_DIR = os.path.join(DATA_DIR, "cards")
OUTPUT_FILE = os.path.join(CARDS_DIR, "unknown_cards.csv")

def main():
    print("Scanning card database for missing types...")
    
    paths = [
        os.path.join(CARDS_DIR, "cards.json"),
        os.path.join(CARDS_DIR, "cards.extra.json"),
    ]
    
    # Map (set, num) -> raw_item
    merged_data = {}
    
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    for item in data:
                        c_set = item.get("set")
                        c_num = str(item.get("number"))
                        merged_data[(c_set, c_num)] = item
            except Exception as e:
                print(f"Error loading {path}: {e}")
                
    unknowns = []
    
    for (c_set, c_num), item in merged_data.items():
        raw_type = item.get("type")
        img = item.get("image", "")
        
        # If type is missing or Unknown, it's a candidate
        if not raw_type or raw_type == "Unknown":
            current_evaluated = "Unknown"
            if img.startswith("cPK"):
                current_evaluated = "Pokemon (Heuristic)"
            elif img.startswith("cTR"):
                current_evaluated = "Item (Heuristic)"
            
            # We explicitly want to include "Item (Heuristic)" because "Item" is ambiguous
            # (could be Support/Tool/Stadium) and sorting depends on it.
            # We can exclude Pokemon (Heuristic) if we trust cPK, but let's include all heuristic ones 
            # so user sees what's happening.
            
            unknowns.append({
                "set": c_set,
                "number": c_num,
                "name": item.get("name") or item.get("card_name"),
                "current_type": current_evaluated,
                "manual_type": "" # Placeholder
            })
            
    # Sort
    unknowns.sort(key=lambda x: (x.get("set", ""), str(x.get("number", ""))))
    
    print(f"Found {len(unknowns)} cards requiring type confirmation.")
    
    # Always create file
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["set", "number", "name", "current_type", "manual_type"])
        writer.writeheader()
        writer.writerows(unknowns)
            
    print(f"Generated {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
