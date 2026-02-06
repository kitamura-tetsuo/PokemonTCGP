
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

import logging
logging.basicConfig(level=logging.INFO)

from src.simulator import run_simulation, DECKS_DIR

def test_simulation():
    # We'll use two of the example decks in the simulator repo for a quick test
    deck1_path = "/workspaces/PokemonTCGP/simulator/deckgym-core/example_decks/mewtwoex.txt"
    deck2_path = "/workspaces/PokemonTCGP/simulator/deckgym-core/example_decks/weezing-arbok.txt"
    
    try:
        print(f"Testing simulation between examples: {os.path.basename(deck1_path)} and {os.path.basename(deck2_path)}")
        
        # Run a small simulation
        wr = run_simulation(deck1_path, deck2_path, num_games=20)
        
        if wr is not None:
            print(f"Success! Win rate: {wr}%")
            print("Verification PASSED")
        else:
            print("Verification FAILED: Could not get win rate")
            
    except Exception as e:
        print(f"Verification ERROR: {e}")

if __name__ == "__main__":
    test_simulation()
