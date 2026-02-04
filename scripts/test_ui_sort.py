import os
import sys

# Add the project root to sys.path to allow importing from src
sys.path.append(os.getcwd())

from src.ui import sort_card_ids

def test_sort_card_ids():
    # Test case 1: Basic types (Pokemon, Goods, Support)
    # A1_1: Bulbasaur (Pokemon)
    # A1a_64: Pokémon Flute (Goods)
    # A1a_67: Blue (Support)
    input_ids = ["A1a_67", "A1_1", "A1a_64"]
    expected_order = ["A1_1", "A1a_64", "A1a_67"]
    
    sorted_ids = sort_card_ids(input_ids)
    print(f"Input: {input_ids}")
    print(f"Sorted: {sorted_ids}")
    print(f"Expected: {expected_order}")
    
    assert sorted_ids == expected_order, f"Test Case 1 Failed! Got {sorted_ids}"
    
    # Test case 2: Duplicate types (Pokemon/Pokemon)
    # A1_1: Bulbasaur
    # A1_2: Ivysaur
    input_ids = ["A1_2", "A1_1"]
    expected_order = ["A1_1", "A1_2"]
    
    sorted_ids = sort_card_ids(input_ids)
    print(f"\nInput: {input_ids}")
    print(f"Sorted: {sorted_ids}")
    print(f"Expected: {expected_order}")
    
    assert sorted_ids == expected_order, f"Test Case 2 Failed! Got {sorted_ids}"

    # Test case 3: Empty and single items
    assert sort_card_ids([]) == []
    assert sort_card_ids(["A1_1"]) == ["A1_1"]

    # Test case 4: Non-existent IDs (should be at the end as 'Unknown' and sorted by ID)
    input_ids = ["XYZ_123", "A1_1"]
    expected_order = ["A1_1", "XYZ_123"]
    sorted_ids = sort_card_ids(input_ids)
    assert sorted_ids == expected_order

    print("\nAll tests for sort_card_ids passed!")

if __name__ == "__main__":
    try:
        test_sort_card_ids()
    except AssertionError as e:
        print(f"\nAssertion error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        sys.exit(1)
