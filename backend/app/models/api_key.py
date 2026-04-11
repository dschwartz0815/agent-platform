"""
ApiKey ORM model — per-org API keys with scope list.

key_prefix is stored in plaintext for lookup (first 16 chars of the key, e.g.
'ap_live_abcd1234'). key_hash is a bcrypt hash of the full key — we can't look
up by hash directly because bcrypt is randomized, so the auth path:
  1. extract prefix from incoming bearer token
  2. SELECT * FROM api_keys WHERE key_prefix = ?
  3. verify each candidate via bcrypt.checkpw(full_key, row.key_hash)

This pattern (prefix lookup + hash verify) is how GitHub, Stripe, and Vercel
handle API key authentication.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Lookup index: first 16 chars of the plaintext key (e.g. "ap_live_abcd1234").
    # Not a secret on its own — shown in the UI for key identification.
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    # bcrypt hash of the full plaintext key
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Last 4 chars of the plaintext key — for UI display (e.g. "…xy9z")
    key_last4: Mapped[str] = mapped_column(String(4), nullable=False)

    # List of graph UUIDs (as strings) or the literal ["*"] for full access
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)

    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
