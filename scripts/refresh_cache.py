
import os
import sys
import logging
import argparse


# Ensure project root is in path
sys.path.append(os.getcwd())

from src.data import _scan_and_aggregate

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Refresh daily exact stats cache.')
    parser.add_argument('--init', action='store_true', help='Refresh all history (approx 10 years) instead of recent 90 days.')
    args = parser.parse_args()

    days_back = 90
    if args.init:
        days_back = 3650 # ~10 years

    logger.info(f"Refreshing daily exact stats cache (days_back={days_back})...")
    try:
        # scan_and_aggregate(days_back=30, force_refresh=True)
        # We use force_refresh=True to ensure everything is recalculated correctly
        _scan_and_aggregate(days_back=days_back, force_refresh=True, update_cache=True)
        logger.info("✅ Cache refreshed successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to refresh cache: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
