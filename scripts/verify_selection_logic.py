import pandas as pd
import numpy as np

def test_selection_logic():
    # Create mock data with 20 archetypes and 20 days
    n_rows = 20
    n_cols = 20
    cols = [f"Arch_{i}" for i in range(n_cols)]
    data = np.zeros((n_rows, n_cols))
    
    # Add small background values to all archetypes so they can be selected
    data += 0.1
    
    # Arch_0 and Arch_1 are always top 2
    data[:, 0] = 30
    data[:, 1] = 20
    
    # Arch_2 is top at start only
    data[0, 2] = 15
    
    # Arch_3 is top at 1/4 only
    data[n_rows // 4, 3] = 15
    
    # Arch_4 is top at 1/2 only
    data[n_rows // 2, 4] = 15
    
    # Arch_5 is top at 3/4 only
    data[(3 * n_rows) // 4, 5] = 15
    
    # Arch_6 is top at end only
    data[n_rows - 1, 6] = 15
    
    df = pd.DataFrame(data, columns=cols)
    
    # Logic to select 12 archetypes based on 5 time points
    MAX_ARCHS = 12
    n_rows = len(df)
    
    indices = [0, n_rows // 4, n_rows // 2, (3 * n_rows) // 4, n_rows - 1]
    indices = sorted(list(set([max(0, min(i, n_rows - 1)) for i in indices])))
    print(f"Indices: {indices}")
    
    ranked_at_points = [df.iloc[idx].sort_values(ascending=False) for idx in indices]
    selected_archetypes = []
    
    # 1. Top 2 decks from each point
    for rank in range(2):
        for point_data in ranked_at_points:
            if rank < len(point_data):
                arch = point_data.index[rank]
                if arch not in selected_archetypes and point_data[arch] > 0:
                    selected_archetypes.append(arch)
                    if len(selected_archetypes) >= MAX_ARCHS:
                        break
        if len(selected_archetypes) >= MAX_ARCHS:
            break
            
    # 2. Fill remaining until 12
    if len(selected_archetypes) < MAX_ARCHS:
        for rank in range(2, len(df.columns)):
            found_at_this_rank = False
            for point_data in ranked_at_points:
                if rank < len(point_data):
                    found_at_this_rank = True
                    arch = point_data.index[rank]
                    if arch not in selected_archetypes and point_data[arch] > 0:
                        selected_archetypes.append(arch)
                        if len(selected_archetypes) >= MAX_ARCHS:
                            break
            if len(selected_archetypes) >= MAX_ARCHS or not found_at_this_rank:
                break
    
    print(f"Selected Archetypes: {selected_archetypes}")
    
    # Expected: Arch_0, Arch_1 (rank 0), 
    # then Arch_2, Arch_3, Arch_4, Arch_5, Arch_6 (rank 1 at different points)
    # Total 7 decks so far.
    # Then it should pick 5 more from any point.
    
    assert "Arch_0" in selected_archetypes
    assert "Arch_1" in selected_archetypes
    assert "Arch_2" in selected_archetypes
    assert "Arch_3" in selected_archetypes
    assert "Arch_4" in selected_archetypes
    assert "Arch_5" in selected_archetypes
    assert "Arch_6" in selected_archetypes
    assert len(selected_archetypes) == 12

if __name__ == "__main__":
    test_selection_logic()
    print("Test passed!")
