import re

def natural_sort_key(s):
    """Helper to sort strings with embedded numbers naturally (e.g. A1-1 < A1-10)."""
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', s)]

def test_sorting():
    # Scenario 1: Numeric suffixes
    ids = ["A1_10", "A1_1", "A1_2"]
    sorted_ids = sorted(ids, key=natural_sort_key)
    print(f"Scenario 1: {ids} -> {sorted_ids}")
    assert sorted_ids == ["A1_1", "A1_2", "A1_10"]

    # Scenario 2: Prefixes and separators
    ids = ["Promo-A1_1", "A1_1", "A1-A_1"]
    sorted_ids = sorted(ids, key=natural_sort_key)
    print(f"Scenario 2: {ids} -> {sorted_ids}")
    # A1 < A1-A < Promo-A1
    assert sorted_ids[0] == "A1_1"

    # Scenario 3: Multiple numbers
    ids = ["A1_1_10", "A1_1_2"]
    sorted_ids = sorted(ids, key=natural_sort_key)
    print(f"Scenario 3: {ids} -> {sorted_ids}")
    assert sorted_ids == ["A1_1_2", "A1_1_10"]

    print("All tests passed!")

if __name__ == "__main__":
    test_sorting()
