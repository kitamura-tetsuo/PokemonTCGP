
import hashlib
import json

def compute_deck_signature(cards):
    """
    Compute a unique hash for a deck list, ignoring order.

    Args:
        cards: List of card dictionaries (must have name, set, number, count).

    Returns:
        hash_str: A short hash string.
        normalized_items: List of normalized card dicts.
    """
    # Normalize items: (name, set, number, count)
    normalized_items = []

    for card in cards:
        if isinstance(card, str):
            name = card
            set_code = "Energy"
            number = "000"
            count = 1
        elif isinstance(card, dict):
            name = card.get("name", "Unknown")
            set_code = card.get("set", "")
            number = str(card.get("number", ""))
            count = card.get("count", 1)
        else:
            continue

        normalized_items.append(
            {"name": name, "set": set_code, "number": number, "count": count}
        )

    # Sort the list to ensure consistent hashing regardless of input order
    normalized_items.sort(key=lambda x: (x["name"], x["set"], x["number"]))

    # Create a string representation for hashing
    deck_str = json.dumps(normalized_items, separators=(",", ":"))

    # Compute SHA256 hash
    full_hash = hashlib.sha256(deck_str.encode("utf-8")).hexdigest()

    # Return first 8 chars as signature
    return full_hash[:8], normalized_items
