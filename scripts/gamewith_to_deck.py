#!/usr/bin/env python3
import sys
import os
import re
import urllib.request
import urllib.parse
from collections import Counter
import json
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import load_enriched_cards
from src.hashing import compute_deck_signature
from src.simulator import load_deckgym_db, get_energy_type_from_db

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def get_gamewith_card_mapping(base_url):
    req = urllib.request.Request(base_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to fetch {base_url}: {e}")
        sys.exit(1)
        
    matches = re.finditer(r"{id:'(\d+)',n:'([^']+)',c:'([^']*)',t:'([^']*)',r:'([^']+)'", html)
    gw_map = {}
    for m in matches:
        gw_map[m.group(1)] = {
            'name_ja': m.group(2),
            'type': m.group(4),
            'r': m.group(5)
        }
        
    if not gw_map:
        logger.error("Could not find GameWith card mapping in the HTML.")
        sys.exit(1)
        
    return gw_map

def find_card_by_name_ja(name_ja, db, rarity_target=None, type_target=None, extra_info=None):
    sorted_cards = sorted(db.values(), key=lambda x: (x.get("set", ""), str(x.get("number", ""))))
    matches = []
    
    # Optional filtering by rarity and type
    if rarity_target and extra_info:
        for info in sorted_cards:
            if info.get("name_ja") == name_ja:
                c_set = info.get("set")
                c_num = str(info.get("number"))
                ex_info = extra_info.get((c_set, c_num), {})
                c_rarity = ex_info.get("rarity")
                c_element = ex_info.get("element", "").lower()
                
                # Check PROMO sets correctly - if target is PROMO, only match PROMO set or 'Promo' rarity
                if rarity_target == "PROMO":
                    rarity_match = ("PROMO" in c_set or "P-A" in c_set)
                else:
                    rarity_match = (c_rarity == rarity_target)
                    
                type_match = (not type_target or not c_element or c_element == type_target)
                
                if rarity_match and type_match:
                    matches.append(info)
                    
    # Fallback: try mapping solely by rarity if type doesn't perfectly align and no matches found
    if not matches and rarity_target and extra_info:
        for info in sorted_cards:
            if info.get("name_ja") == name_ja:
                c_set = info.get("set")
                c_num = str(info.get("number"))
                ex_info = extra_info.get((c_set, c_num), {})
                c_rarity = ex_info.get("rarity")
                if rarity_target == "PROMO":
                    if "PROMO" in c_set or "P-A" in c_set:
                        matches.append(info)
                elif c_rarity == rarity_target:
                    matches.append(info)
                    
    # Strict fallback if no rarity targeting was applied or it yielded nothing at all
    if not matches:
        for info in sorted_cards:
            if info.get("name_ja") == name_ja:
                matches.append(info)
                
    if not matches:
        return None
        
    if len(matches) > 1:
        # Create a descriptive list of sets/numbers that matched to help debugging
        options = [f"{m.get('set')} {m.get('number')}" for m in matches]
        raise ValueError(f"Ambiguous card match for '{name_ja}'. Multiple variants found: {options}")
        
    return matches[0]

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 gamewith_to_deck.py <gamewith_url>")
        sys.exit(1)
        
    full_url = sys.argv[1]
    parsed_url = urllib.parse.urlparse(full_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    
    # Extract ids from hash fragment
    # GameWith often puts ids in fragment e.g., #ids=123_456&e=psychic
    qs_to_parse = parsed_url.fragment if parsed_url.fragment else parsed_url.query
    fragment_qs = urllib.parse.parse_qs(qs_to_parse)
    
    if 'ids' not in fragment_qs:
        logger.error("No 'ids' parameter found in the URL. (e.g. #ids=123...)")
        sys.exit(1)
        
    gw_ids_str = fragment_qs['ids'][0]
    gw_ids = [i for i in gw_ids_str.split('_') if i]
    id_counts = Counter(gw_ids)
    
    logger.info("Fetching GameWith ID mapping...")
    gw_map = get_gamewith_card_mapping(base_url)
    db = load_enriched_cards()
    
    cards_for_hashing = []
    deckgym_lines = []
    
    extra_cards_path = os.path.join(os.getcwd(), "data", "cards", "cards.extra.json")
    element_map = {}
    extra_card_info = {}
    if os.path.exists(extra_cards_path):
        try:
            with open(extra_cards_path, "r") as f:
                extra_data = json.load(f)
                for item in extra_data:
                    c_set = item.get("set")
                    c_num = str(item.get("number"))
                    if c_set and c_num:
                        extra_card_info[(c_set, c_num)] = item
                        element = item.get("element")
                        if element:
                            element_map[(c_set, c_num)] = element.capitalize()
        except Exception as e:
            logger.warning(f"Failed to load extra card data: {e}")

    energy_types = set()
    dg_db = load_deckgym_db()
    
    r_map = {
        'd1': 'C', 'd2': 'U', 'd3': 'R', 'd4': 'RR',
        's1': 'AR', 's2': 'SR', 's3': 'SAR', 'ur': 'UR', 'pr': 'PROMO'
    }
    
    t_map = {
        '草': 'grass', '炎': 'fire', '水': 'water', '雷': 'lightning', '超': 'psychic',
        '闘': 'fighting', '悪': 'dark', '鋼': 'metal', '竜': 'dragon', '無': 'colorless'
    }

    for gw_id, count in id_counts.items():
        gw_card = gw_map.get(gw_id)
        if not gw_card:
            logger.error(f"Could not find GameWith properties for GameWith ID {gw_id}")
            sys.exit(1)
            
        name_ja = gw_card['name_ja']
        r_val = gw_card['r']
        t_val = gw_card.get('type')
        
        rarity_target = r_map.get(r_val)
        type_target = t_map.get(t_val)
            
        try:
            card_info = find_card_by_name_ja(name_ja, db, rarity_target, type_target, extra_card_info)
            if not card_info:
                logger.error(f"Could not find local database entry for card '{name_ja}'")
                sys.exit(1)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
            
        c_set = card_info.get("set")
        c_num = card_info.get("number")
        name_en = card_info.get("name")
        
        cards_for_hashing.append({
            "name": name_en,
            "set": c_set,
            "number": str(c_num),
            "count": count
        })
        
        # DeckGym formatting logic
        if name_ja and name_ja != name_en:
            full_name = f"{name_en} ({name_ja})"
        else:
            full_name = name_en
            
        try:
            formatted_num = f"{int(c_num):03d}"
        except:
            formatted_num = str(c_num)
            
        deckgym_lines.append(f"{count} {full_name} {c_set} {formatted_num}")
        
        # Element resolution
        if card_info.get("type") == "Pokemon":
            e_type = element_map.get((c_set, str(c_num)))
            if not e_type:
                e_type = get_energy_type_from_db(name_en, c_set, c_num, dg_db)
            if e_type and e_type != "Colorless":
                energy_types.add(e_type)
                
    # If energy passed via GameWith URL query or fragment, add it?
    e_param = fragment_qs.get('e', [])
    if e_param:
        for e in e_param[0].split('_'):
            energy_types.add(e.capitalize())

    energy_header = ", ".join(sorted(list(energy_types)))
    if not energy_header:
        energy_header = "Colorless"
        
    deckgym_output = [f"Energy: {energy_header}"] + deckgym_lines
    
    # Compute signature
    signature, _ = compute_deck_signature(cards_for_hashing)
    logger.info(f"Computed Deck Signature: {signature}")
    
    # Save to train_data
    train_data_dir = "train_data"
    os.makedirs(train_data_dir, exist_ok=True)
    output_path = os.path.join(train_data_dir, f"{signature}.txt")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(deckgym_output) + "\n")
        
    logger.info(f"Successfully saved DeckGym file to {output_path}")

if __name__ == "__main__":
    main()
