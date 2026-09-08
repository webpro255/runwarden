"""Nonce tests."""

import string

from runwarden.nonce import NONCE_HEX_CHARS, generate


def test_nonce_is_sixteen_characters():
    assert len(generate()) == 16
    assert NONCE_HEX_CHARS == 16


def test_nonce_is_lowercase_hex_only():
    nonce = generate()
    allowed = set(string.hexdigits.lower())
    assert set(nonce) <= allowed
    assert nonce == nonce.lower()


def test_two_calls_differ():
    assert generate() != generate()


def test_many_calls_are_unique():
    """A repeat inside a small sample would mean the generator is not random."""
    assert len({generate() for _ in range(500)}) == 500
