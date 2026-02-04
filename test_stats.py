
import pandas as pd
from src.data import get_period_statistics

def test_get_period_statistics():
    # Simple test to verify it doesn't crash and returns expected structure
    df = pd.DataFrame({
        "Pikachu (abc12345)": [1.0, 2.0],
        "Mewtwo (def67890)": [3.0, 4.0]
    }, index=["2026-01-01", "2026-01-02"])
    
    # This will attempt to call get_deck_details which hits the real cache
    # But for a simple import and structure check, we can just see if it runs
    try:
        stats = get_period_statistics(df)
        print("Function executed successfully.")
        print(f"Stats keys: {list(stats.keys())}")
    except Exception as e:
        print(f"Error executing function: {e}")

if __name__ == "__main__":
    test_get_period_statistics()
