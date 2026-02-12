import sys
import os
import csv
import shutil
import logging
import pandas as pd
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import (
    load_enriched_sets,
    get_daily_share_data,
    get_period_statistics,
)
from src.utils import calculate_confidence_interval
from src.simulator import convert_signature_to_deckgym, DECKS_DIR

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 create_training_set.py <num_student> <num_teacher>")
        sys.exit(1)

    try:
        num_student = int(sys.argv[1])
        num_teacher = int(sys.argv[2])
    except ValueError:
        print("Error: num_student and num_teacher must be integers.")
        sys.exit(1)

    # 1. Load latest set
    logger.info("Loading latest set info...")
    enriched_sets = load_enriched_sets()
    if not enriched_sets:
        logger.error("No enriched sets found.")
        sys.exit(1)
    
    # Pre-sort chronologically to find the latest
    chronological_sets = sorted(enriched_sets, key=lambda x: x.get("releaseDate", "0000-00-00"), reverse=True)
    latest_set = chronological_sets[0]
    latest_set_code = latest_set.get("code")
    latest_set_release = latest_set.get("releaseDate")
    
    logger.info(f"Latest set: {latest_set_code} (Released: {latest_set_release})")

    # 2. Get deck statistics for the latest set's period
    logger.info(f"Fetching statistics for period starting {latest_set_release}...")
    df = get_daily_share_data(
        start_date=latest_set_release,
        standard_only=True
    )
    
    if df.empty:
        logger.error("No data found for the latest set period.")
        sys.exit(1)

    stats_map = get_period_statistics(
        df,
        start_date=latest_set_release,
        clustered=False
    )

    # 3. Process and sort decks
    logger.info("Processing deck statistics and calculating lower CI...")
    deck_list = []
    for label, info in stats_map.items():
        # Label format: "Archetype Name (signature)"
        try:
            name = label.split("(")[0].strip()
            sig = label.split("(")[1].split(")")[0]
        except (IndexError, ValueError):
            logger.warning(f"Skipping malformed label: {label}")
            continue

        stats = info.get("stats", {})
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        ties = stats.get("ties", 0)
        total = wins + losses + ties
        
        lower_ci, _ = calculate_confidence_interval(wins, total)
        
        deck_list.append({
            "signature": sig,
            "lower_ci": lower_ci,
            "archetype": name
        })

    # Sort by lower_ci descending
    deck_list.sort(key=lambda x: x["lower_ci"], reverse=True)

    # 4. Filter top decks
    student_decks = deck_list[:num_student]
    teacher_decks = deck_list[:num_teacher]

    # 5. Output CSVs
    logger.info("Generating CSV files...")
    headers = ["signature", "lower_ci", "archetype"]
    
    def write_csv(filename, data):
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for d in data:
                writer.writerow([d["signature"], f"{d['lower_ci']:.2f}", d["archetype"]])

    write_csv("student.csv", student_decks)
    write_csv("teacher.csv", teacher_decks)
    logger.info(f"Created student.csv ({len(student_decks)} entries) and teacher.csv ({len(teacher_decks)} entries).")

    # 6. Save card lists to train_data/
    logger.info("Saving deck card lists to train_data/...")
    train_data_dir = "train_data"
    os.makedirs(train_data_dir, exist_ok=True)
    
    # Collect unique signatures
    unique_sigs = set(d["signature"] for d in student_decks) | set(d["signature"] for d in teacher_decks)
    
    for sig in unique_sigs:
        try:
            # convert_signature_to_deckgym saves to DECKS_DIR (/workspaces/PokemonTCGP/simulator/decks)
            output_path = convert_signature_to_deckgym(sig)
            
            # Destination path in train_data/
            dest_path = os.path.join(train_data_dir, os.path.basename(output_path))
            
            # Move if it's not already there (which it shouldn't be based on DECKS_DIR)
            if os.path.abspath(output_path) != os.path.abspath(dest_path):
                shutil.move(output_path, dest_path)
                logger.info(f"Saved card list for {sig} to {dest_path}")
        except Exception as e:
            logger.error(f"Failed to convert signature {sig}: {e}")

    logger.info("Done!")

if __name__ == "__main__":
    main()
