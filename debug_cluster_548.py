
import sys
import os
import json
sys.path.append(os.getcwd())
from src.data import get_cluster_details, _get_all_signatures

# Mock the period if needed, or just pass None to get all
cid = "548"

print(f"--- Debugging Cluster {cid} ---")
details = get_cluster_details(cid)

if not details:
    print("Cluster details returned None")
else:
    print(f"Name: {details['name']}")
    print(f"Rep Sig: {details['representative_sig']}")
    print(f"Cards count: {len(details.get('cards', []))}")
    if details.get('cards'):
        print(f"First card: {details['cards'][0]}")
    
    print(f"Signatures found: {len(details['signatures'])}")
    print(f"Signature keys: {list(details['signatures'].keys())}")
    
    # Check if rep sig is in signatures
    if details['representative_sig'] in details['signatures']:
        print("Rep sig IS in filtered signatures.")
    else:
        print("Rep sig is NOT in filtered signatures.")

    # Check cards of first signature
    if details['signatures']:
        first_sig = list(details['signatures'].keys())[0]
        first_deck = details['signatures'][first_sig]
        print(f"First sig ({first_sig}) cards: {len(first_deck.get('cards', []))}")

