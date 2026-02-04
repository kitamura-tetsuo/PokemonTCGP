
import subprocess
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def run_script(script_path, args=None):
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)
    
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        logger.error(f"❌ Error running {script_path}")
        return False
    return True

def main():
    logger.info("Starting daily update process...")
    
    # 1. Update tournaments and card database (raw files)
    if not run_script("scripts/update_tournaments.py"):
        sys.exit(1)
        
    # 2. Cleanup cards (remove duplicates, filter sets)
    if not run_script("scripts/cleanup_cards.py"):
        sys.exit(1)

    # 3. Enrich sets (localize set names)
    if not run_script("scripts/enrich_sets.py"):
        sys.exit(1)

    # 4. Enrich cards (ensure translations and types are up to date)
    if not run_script("scripts/enrich_cards.py"):
        sys.exit(1)

    # 5. Refresh cache (scan and aggregate)
    if not run_script("scripts/refresh_cache.py"):
        sys.exit(1)
        
    # 6. Cluster decks
    if not run_script("scripts/cluster_decks.py"):
        sys.exit(1)
        
    logger.info("✅ Daily update process completed successfully.")

if __name__ == "__main__":
    main()
