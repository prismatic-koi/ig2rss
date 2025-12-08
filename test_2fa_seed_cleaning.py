#!/usr/bin/env python3
"""Test script to verify 2FA seed cleaning works correctly."""

import re
import base64

def clean_seed(totp_seed):
    """Clean TOTP seed the same way as instagram_client.py does."""
    # Remove ALL whitespace characters (spaces, tabs, newlines, etc.)
    seed = re.sub(r'\s+', '', totp_seed.strip())
    
    # Remove common separators
    seed = seed.replace("-", "").replace("_", "")
    
    print(f"Original length: {len(totp_seed)}")
    print(f"Cleaned length: {len(seed)}")
    print(f"Preview: {seed[:4]}...{seed[-4:] if len(seed) > 8 else ''}")
    
    # Try to detect if it's a hex-encoded secret
    if any(c in seed.lower() for c in '89abcdef'):
        print("Detected as hex-encoded, converting to base32...")
        try:
            hex_bytes = bytes.fromhex(seed)
            seed = base64.b32encode(hex_bytes).decode('ascii').rstrip('=')
            print(f"Converted to base32: length={len(seed)}")
        except ValueError as e:
            print(f"Failed to parse as hex: {e}, treating as base32")
    
    # Ensure uppercase for base32
    seed = seed.upper()
    
    return seed

# Test cases
test_seeds = [
    "JBSWY3DPEHPK3PXP",  # No spaces
    "JBSW Y3DP EHPK 3PXP",  # With spaces
    "JBSW\tY3DP\tEHPK\t3PXP",  # With tabs
    "JBSW-Y3DP-EHPK-3PXP",  # With dashes
]

print("Testing seed cleaning:\n")
for i, test_seed in enumerate(test_seeds, 1):
    print(f"Test {i}: {repr(test_seed)}")
    cleaned = clean_seed(test_seed)
    print(f"Result: {cleaned}")
    print()
