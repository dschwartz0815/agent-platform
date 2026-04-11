"""
API key management endpoints.

GET /api/v1/api-keys           — list all keys for the dev org (never includes plaintext)
POST /api/v1/api-keys          — create; returns plaintext ONCE
POST /api/v1/api-keys/{id}/revoke — mark revoked
DELETE /api/v1/api-keys/{id}   — hard delete
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.db import get_db
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreatedOut, ApiKeyOut
from app.services.api_keys import (
    generate_plaintext_key,
    hash_key,
    split_prefix,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.org_id == DEV_ORG_ID)
        .order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ApiKeyCreatedOut, status_code=201)
async def create_api_key(body: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    plaintext = generate_plaintext_key()
    row = ApiKey(
        org_id=DEV_ORG_ID,
        name=body.name,
        key_prefix=split_prefix(plaintext),
        key_hash=hash_key(plaintext),
        key_last4=plaintext[-4:],
        scopes=body.scopes,
        created_by=DEV_USER_ID,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    # Build the response manually so we can include the plaintext field
    return ApiKeyCreatedOut(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        key_prefix=row.key_prefix,
        key_last4=row.key_last4,
        scopes=row.scopes,
        created_by=row.created_by,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        key=plaintext,  # the ONLY time plaintext is ever returned
    )


@router.post("/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_api_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key or key.org_id != DEV_ORG_ID:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(key)
    return key


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key or key.org_id != DEV_ORG_ID:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(key)
    await db.flush()
