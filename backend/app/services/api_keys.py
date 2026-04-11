"""
API key service — generate, hash, verify.

Keys look like: ap_live_<32-char urlsafe token>
Example: ap_live_abcdefgh-1234567-XyZ890qrstuv

Storage:
  - key_prefix (first 16 chars, indexed) — used for lookup
  - key_hash (bcrypt) — used for verification
  - key_last4 (last 4 chars) — for UI display
  - plaintext is returned ONCE at creation and never stored
"""

from __future__ import annotations

import secrets

import bcrypt

PLAINTEXT_PREFIX = "ap_live_"
PREFIX_CHAR_COUNT = 16  # "ap_live_" (8) + first 8 chars of the random tail
SECRET_NBYTES = 24  # token_urlsafe(24) yields ~32 chars


def generate_plaintext_key() -> str:
    """
    Generate a new plaintext API key. Caller is responsible for hashing it
    for storage and returning the plaintext to the user exactly once.
    """
    return PLAINTEXT_PREFIX + secrets.token_urlsafe(SECRET_NBYTES)


def split_prefix(plaintext_key: str) -> str:
    """
    Extract the first PREFIX_CHAR_COUNT (16) characters of the key.
    This is the lookup index stored in api_keys.key_prefix.
    Not a secret — shown in the UI for key identification.
    """
    return plaintext_key[:PREFIX_CHAR_COUNT]


def hash_key(plaintext_key: str) -> str:
    """bcrypt hash for storage. Returns the $2b$... string form."""
    return bcrypt.hashpw(plaintext_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_key(plaintext_key: str, stored_hash: str) -> bool:
    """
    Check a plaintext key against a stored bcrypt hash. Returns False on
    malformed hashes rather than raising, so the auth dependency can treat
    'hash corrupt' as 'auth failed' without leaking a 500.
    """
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(plaintext_key.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
