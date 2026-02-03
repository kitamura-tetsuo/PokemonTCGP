
import unittest
from scripts.cluster_decks import calculate_distance, cluster_decks

class TestClustering(unittest.TestCase):
    def test_distance_rules(self):
        # Pokemon rules: diff count = 0.5 each, unique = 1.0 each
        # Non-Pokemon: diff count = 0.125 each, unique = 0.25 each
        
        # Test 1: Identical decks
        d1 = [{"name": "Pikachu", "type": "Pokemon", "count": 2}]
        d2 = [{"name": "Pikachu", "type": "Pokemon", "count": 2}]
        self.assertEqual(calculate_distance(d1, d2), 0.0)
        
        # Test 2: Pokemon count difference (User's example: Pikachu 2 & Pikachu 1)
        d3 = [{"name": "Pikachu", "type": "Pokemon", "count": 1}]
        self.assertEqual(calculate_distance(d1, d3), 0.5)
        
        # Test 3: Pokemon swap (User's example: Pikachu 2 Zacian 1 vs Pikachu 1 Zacian 2)
        # Pikachu diff: 1 * 0.5 = 0.5
        # Zacian diff: 1 * 0.5 = 0.5
        # Total: 1.0
        d_p2z1 = [
            {"name": "Pikachu", "type": "Pokemon", "count": 2},
            {"name": "Zacian", "type": "Pokemon", "count": 1}
        ]
        d_p1z2 = [
            {"name": "Pikachu", "type": "Pokemon", "count": 1},
            {"name": "Zacian", "type": "Pokemon", "count": 2}
        ]
        self.assertEqual(calculate_distance(d_p2z1, d_p1z2), 1.0)
        
        # Test 4: Pokemon completely different (User's example: Pikachu 1 vs Zacian 1)
        # Pikachu unique: 1 * 1.0 = 1.0
        # Zacian unique: 1 * 1.0 = 1.0
        # Total: 2.0
        d_p1 = [{"name": "Pikachu", "type": "Pokemon", "count": 1}]
        d_z1 = [{"name": "Zacian", "type": "Pokemon", "count": 1}]
        self.assertEqual(calculate_distance(d_p1, d_z1), 2.0)
        
        # Test 5: Non-Pokemon difference
        # Supporter diff: 1 * 0.125 = 0.125
        # Stadium unique: 1 * 0.25 = 0.25
        d_tr1 = [{"name": "Research", "type": "Support", "count": 2}]
        d_tr2 = [
            {"name": "Research", "type": "Support", "count": 1},
            {"name": "Shrine", "type": "Stadium", "count": 1}
        ]
        self.assertEqual(calculate_distance(d_tr1, d_tr2), 0.375)

    def test_clustering_connectivity(self):
        # A-B dist 1.0, B-C dist 1.0, A-C dist 2.0
        # Threshold 1.0 should group them all in one cluster (connected components)
        signatures = {
            "A": {"cards": [{"name": "P1", "type": "Pokemon", "count": 2}], "name": "DeckA"},
            "B": {"cards": [{"name": "P1", "type": "Pokemon", "count": 3}], "name": "DeckB"},
            "C": {"cards": [{"name": "P1", "type": "Pokemon", "count": 4}], "name": "DeckC"}
        }
        # A-B dist = 0.5
        # B-C dist = 0.5
        # A-C dist = 1.0
        # All dist <= 1.0, but let's make it larger
        
        signatures_wide = {
            "A": {"cards": [{"name": "P1", "type": "Pokemon", "count": 2}], "name": "DeckA"},
            "B": {"cards": [{"name": "P1", "type": "Pokemon", "count": 4}], "name": "DeckB"}, # Dist A-B = 1.0
            "C": {"cards": [{"name": "P1", "type": "Pokemon", "count": 6}], "name": "DeckC"}  # Dist B-C = 1.0, A-C = 2.0
        }
        
        clusters = cluster_decks(signatures_wide, threshold=1.0)
        self.assertEqual(len(clusters), 1)
        self.assertIn("A", clusters[0])
        self.assertIn("B", clusters[0])
        self.assertIn("C", clusters[0])

if __name__ == "__main__":
    unittest.main()
