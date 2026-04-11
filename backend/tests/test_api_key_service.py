"""Unit tests for the api_keys service."""

import pytest

from app.services.api_keys import (
    PLAINTEXT_PREFIX,
    PREFIX_CHAR_COUNT,
    generate_plaintext_key,
    hash_key,
    split_prefix,
    verify_key,
)


def test_generate_plaintext_key_format():
    key = generate_plaintext_key()
    assert key.startswith(PLAINTEXT_PREFIX)
    # Plaintext = "ap_live_" + 32-char urlsafe token
    assert len(key) >= PREFIX_CHAR_COUNT + 16


def test_generate_plaintext_key_is_unique():
    keys = {generate_plaintext_key() for _ in range(100)}
    assert len(keys) == 100


def test_split_prefix_returns_first_16_chars():
    key = "ap_live_abcdefghijklmnopqrstuvwxyz1234"
    prefix = split_prefix(key)
    assert prefix == "ap_live_abcdefgh"
    assert len(prefix) == 16


def test_hash_and_verify_roundtrip():
    key = generate_plaintext_key()
    hashed = hash_key(key)

    # bcrypt hashes are prefixed with $2b$ and ~60 chars long
    assert hashed.startswith("$2b$")
    assert len(hashed) >= 50

    assert verify_key(key, hashed) is True
    assert verify_key("ap_live_wrongkey00000000000000000000000000", hashed) is False


def test_hash_same_key_twice_produces_different_hashes():
    """bcrypt uses per-call salts — same input → different hash."""
    key = generate_plaintext_key()
    h1 = hash_key(key)
    h2 = hash_key(key)
    assert h1 != h2
    # But both verify against the same plaintext
    assert verify_key(key, h1)
    assert verify_key(key, h2)


def test_verify_rejects_malformed_hash():
    key = generate_plaintext_key()
    # Pass something that isn't a valid bcrypt hash
    assert verify_key(key, "not-a-real-hash") is False
    assert verify_key(key, "") is False
