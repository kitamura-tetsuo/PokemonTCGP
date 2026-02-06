
import json
import os
import subprocess
import re
import logging
from src.data import get_deck_details_by_signature, _get_all_signatures

logger = logging.getLogger(__name__)

DECKGYM_DIR = "/workspaces/deckgym-core"
DECKS_DIR = os.path.join(os.getcwd(), "simulator", "decks")
DECKGYM_DB = os.path.join(DECKGYM_DIR, "database.json")
CARGO_PATH = os.path.expanduser("~/.cargo/bin/cargo")

def load_deckgym_db():
    if not os.path.exists(DECKGYM_DB):
        logger.error(f"DeckGym database not found: {DECKGYM_DB}")
        return []
    with open(DECKGYM_DB, "r") as f:
        return json.load(f)

def get_energy_type_from_db(card_name, card_set, card_num, db):
    # DeckGym IDs are like "A1 001"
    try:
        dg_id = f"{card_set} {int(card_num):03d}"
    except:
        dg_id = f"{card_set} {card_num}"
        
    for item in db:
        if "Pokemon" in item:
            p = item["Pokemon"]
            if p.get("id") == dg_id or p.get("name") == card_name:
                return p.get("energy_type")
    return None

def convert_signature_to_deckgym(signature, output_filename=None):
    """
    Converts a deck signature to a DeckGym .txt file.
    Returns the absolute path to the created file.
    """
    if not output_filename:
        output_filename = f"{signature}.txt"
    
    output_path = os.path.join(DECKS_DIR, output_filename)
    os.makedirs(DECKS_DIR, exist_ok=True)
    
    details_map = get_deck_details_by_signature([signature])
    details = details_map.get(signature)
    
    if not details or "cards" not in details:
        raise ValueError(f"Could not find details for signature: {signature}")
        
    cards = details["cards"]
    db = load_deckgym_db()
    
    # Determine primary energy type (heuristic)
    energy_counts = {}
    for c in cards:
        if c.get("type") == "Pokemon":
            e_type = get_energy_type_from_db(c.get("name"), c.get("set"), c.get("number"), db)
            if e_type:
                energy_counts[e_type] = energy_counts.get(e_type, 0) + c.get("count", 1)
    
    primary_energy = "Colorless"
    if energy_counts:
        primary_energy = max(energy_counts, key=energy_counts.get)
        
    # Write file
    with open(output_path, "w") as f:
        f.write(f"Energy: {primary_energy}\n")
        for c in cards:
            c_set = c.get("set")
            c_num = c.get("number")
            count = c.get("count", 1)
            # DeckGym expects "A1 001" format
            try:
                formatted_num = f"{int(c_num):03d}"
            except:
                formatted_num = c_num
            f.write(f"{count} {c_set} {formatted_num}\n")
            
    return output_path

def run_simulation(deck1_path, deck2_path, num_games=100):
    """
    Runs DeckGym simulation and returns win rate of deck1.
    """
    if not os.path.exists(CARGO_PATH):
        raise RuntimeError("Cargo not found at expected path.")
        
    cmd = [
        CARGO_PATH, "run", "--manifest-path", os.path.join(DECKGYM_DIR, "Cargo.toml"),
        "--", "simulate", deck1_path, deck2_path, "--num", str(num_games), "--players", "e,e"
    ]
    
    logger.info(f"Running simulation: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Log output for debugging regex
    logger.info(f"Simulation STDOUT:\n{result.stdout}")
    logger.info(f"Simulation STDERR:\n{result.stderr}")
    
    if result.returncode != 0:
        error_msg = f"Simulation failed with return code {result.returncode}.\n"
        if "panicked" in result.stderr:
            panic_match = re.search(r"panicked at (.+)", result.stderr)
            if panic_match:
                error_msg += f"Panic: {panic_match.group(1)}\n"
        raise RuntimeError(f"{error_msg}\nSTDERR:\n{result.stderr}")
        
    # Parse output for win rate
    # DeckGym output might go to stdout or stderr depending on terminal/environment
    combined_output = result.stdout + result.stderr
    
    # Example output: "Player 0 won: 2 (20.00%)"
    match = re.search(r"Player 0 won: \d+ \(([\d.]+)%\)", combined_output)
    if match:
        return float(match.group(1))
    
    # Example output: "Win rate of example_decks/mewtwoex.txt: 50.00% (500/1000)"
    match = re.search(r"Win rate of .+: ([\d.]+)%", combined_output)
    if match:
        return float(match.group(1))
    
    # Try another pattern if output format is different
    match = re.search(r"Win rate: ([\d.]+)%", combined_output)
    if match:
        return float(match.group(1))
        
    raise RuntimeError(f"Could not parse win rate from output.\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
