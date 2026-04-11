"""Pydantic schemas for API keys.

ApiKeyCreatedOut is the response for POST /api-keys and contains the plaintext
`key` field — this is the ONLY time the plaintext is ever returned. Subsequent
reads return ApiKeyOut which omits it.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    """Body for POST /api/v1/api-keys."""
    name: str = Field(min_length=1, max_length=255)
    # Either ["*"] for full access or a list of graph UUID strings.
    # The frontend sends either the wildcard or an explicit list; not both.
    scopes: list[str] = Field(min_length=1)


class ApiKeyOut(BaseModel):
    """List/read response — no plaintext ever."""
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    key_prefix: str
    key_last4: str
    scopes: list[str]
    created_by: uuid.UUID
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreatedOut(ApiKeyOut):
    """
    Response for POST /api/v1/api-keys — includes the plaintext `key` field.
    This is the ONLY time the full key is ever exposed. The caller must save it
    immediately; subsequent reads will never include it.
    """
    key: str  # plaintext, shown once
