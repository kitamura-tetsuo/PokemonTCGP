"""Compatibility namespace for scripts using the former ``src`` imports.

The web entrypoint imports only ``pokemontcgp`` so a running Streamlit process
cannot retain the pre-snapshot implementations under its old module names.
"""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "pokemontcgp")]
