
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.simulator import convert_signature_to_deckgym

def test_conversion():
    # Mewtwo-Gardevoir sample signature (heuristic)
    # Using a valid signature found in the cache
    test_sig = "8b2904f4"
    
    try:
        print(f"Testing conversion for signature: {test_sig}")
        output_path = convert_signature_to_deckgym(test_sig)
        print(f"Success! Deck file created at: {output_path}")
        
        with open(output_path, "r") as f:
            content = f.read()
            print("--- Content ---")
            print(content)
            print("---------------")
            
        if "Energy:" in content and test_sig in output_path:
            print("Verification PASSED")
        else:
            print("Verification FAILED: Missing Energy header or wrong path")
            
    except Exception as e:
        print(f"Verification ERROR: {e}")

if __name__ == "__main__":
    test_conversion()
