"""
API key authentication dependency + scope-check helper.

Usage in a FastAPI route:

    from fastapi import Depends
    from app.security.auth import authenticate_api_key, check_graph_scope
    from app.models.api_key import ApiKey

    @router.post("/v1/run/{org}/{slug}")
    async def handler(
        org: str,
        slug: str,
        ...
        api_key: ApiKey = Depends(authenticate_api_key),
        db: AsyncSession = Depends(get_db),
    ):
        # after resolving graph_id from (org, slug)
        check_graph_scope(api_key, graph_id)  # raises 404 on mismatch
        ...

Scope-mismatch and graph-not-found both surface as 404 so external callers
can't enumerate what they can't access (security spec §6.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.api_key import ApiKey
from app.services.api_keys import (
    PLAINTEXT_PREFIX,
    split_prefix,
    verify_key,
)


async def authenticate_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """
    Extract and verify the API key from the Authorization header.

    Returns the ApiKey row on success. Raises:
      - 401 if header is missing, malformed, or the key doesn't match any row
      - 401 if the key is revoked
    Caller is responsible for calling check_graph_scope after resolving the
    target graph, which raises 404 for scope mismatch.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = header[len("Bearer "):].strip()
    if not token or not token.startswith(PLAINTEXT_PREFIX):
        raise HTTPException(status_code=401, detail="Invalid API key")

    prefix = split_prefix(token)
    # Lookup candidate rows by prefix (cheap index hit); verify each via bcrypt.
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix)
    )
    candidates = result.scalars().all()
    for candidate in candidates:
        if verify_key(token, candidate.key_hash):
            if candidate.revoked_at is not None:
                raise HTTPException(status_code=401, detail="API key revoked")
            # Touch last_used_at (non-blocking from the caller's perspective).
            candidate.last_used_at = datetime.now(timezone.utc)
            await db.flush()
            return candidate

    raise HTTPException(status_code=401, detail="Invalid API key")


def check_graph_scope(api_key: ApiKey, graph_id: uuid.UUID) -> None:
    """
    Raise HTTPException(404) if the api key's scope doesn't include graph_id.

    The spec uses 404 (not 403) for scope mismatch so callers can't enumerate
    which graphs exist but they lack access to — both "graph not found" and
    "out of scope" surface as identical 404s to the outside world.
    """
    scopes = api_key.scopes or []
    if "*" in scopes:
        return
    if str(graph_id) in scopes:
        return
    raise HTTPException(status_code=404, detail="Graph not found")
