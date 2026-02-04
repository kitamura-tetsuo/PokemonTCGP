
import os
import sys
import logging

# Ensure project root is in path
sys.path.append(os.getcwd())

from src.data import _scan_and_aggregate

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Refreshing daily exact stats cache...")
    try:
        # scan_and_aggregate(days_back=30, force_refresh=True)
        # We use force_refresh=True to ensure everything is recalculated correctly
        _scan_and_aggregate(days_back=90, force_refresh=True, update_cache=True)
        logger.info("✅ Cache refreshed successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to refresh cache: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
