"""Nonce generation.

The nonce is the only thing that has to travel between two runs for a channel to
count as open. It is a marker, not a secret, but it is generated with `secrets`
so that a surface cannot produce it by accident or by guessing.
"""

import secrets

NONCE_HEX_CHARS = 16


def generate() -> str:
    """Return a fresh nonce as 16 lowercase hex characters."""
    return secrets.token_hex(NONCE_HEX_CHARS // 2)
