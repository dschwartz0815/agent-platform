# Plan C — API Keys + Public Run Endpoints (Sync & Stream)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Graphs can be invoked as public HTTP APIs — `POST /v1/run/{org}/{slug}` (sync JSON response) or `POST /v1/run/{org}/{slug}?mode=stream` (SSE) — authenticated with per-org API keys that are hashed at rest, scoped to specific graphs, and managed via UI with show-once plaintext reveal.

**Architecture:** A new `api_keys` table holds `key_prefix` (indexed, for lookup) + `key_hash` (bcrypt, for verification) + `scopes` (list of graph UUIDs or `"*"`). A FastAPI dependency authenticates the `Authorization: Bearer ap_live_...` header on every `/v1/*` route: parse, lookup by prefix, verify hash, touch `last_used_at`, return the row. A thin helper checks scope against the resolved graph id and raises 404 (deliberately not 403) when out of scope so callers can't enumerate what they can't access. Request bodies on public endpoints are validated against `graph.input_schema` via `jsonschema` before execution. Sync mode buffers the SSE output and returns a single JSON response; stream mode is the existing SSE passthrough. Plaintext keys are generated once (`ap_live_` + 32-char secret), returned verbatim in the POST response and never stored — only the bcrypt hash and a prefix display strip persist. The frontend adds a top-level **API Keys** page, a show-once reveal modal, and a Keys tab inside GraphDetail filtered to keys with scope over the current graph.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic v2 (backend); bcrypt, jsonschema (new deps); pytest + pytest-asyncio + aiosqlite (tests); React 19 + TanStack React Query + axios (frontend).

**Parent spec:** `docs/superpowers/specs/2026-04-11-graph-as-api-design.md`

**Depends on:** Plan A (versioning) and Plan B (runs persistence) — both merged to `main`.

---

## File structure

### Backend

**New:**
- `backend/alembic/versions/d5e6f7a8b9c0_api_keys.py` — migration
- `backend/app/models/api_key.py` — `ApiKey` ORM model
- `backend/app/schemas/api_key.py` — `ApiKeyCreate`, `ApiKeyOut`, `ApiKeyCreatedOut` (plaintext once)
- `backend/app/services/api_keys.py` — `generate_plaintext_key`, `hash_key`, `verify_key`, `split_prefix`
- `backend/app/security/__init__.py` — package marker
- `backend/app/security/auth.py` — `authenticate_api_key` FastAPI dependency + `check_graph_scope` helper
- `backend/app/services/schema_validation.py` — `validate_against_schema` helper wrapping `jsonschema`
- `backend/app/routers/api_keys.py` — `GET/POST/DELETE /api/v1/api-keys`, `POST /api/v1/api-keys/{id}/revoke`
- `backend/app/routers/public_runs.py` — `POST /v1/run/{org}/{slug}` (sync + `?mode=stream`)
- `backend/tests/test_api_key_service.py` — unit tests for generate/hash/verify
- `backend/tests/test_api_keys_api.py` — integration tests for management endpoints
- `backend/tests/test_public_runs_auth.py` — auth dependency tests (missing/invalid/revoked/out-of-scope/wildcard)
- `backend/tests/test_public_runs_execution.py` — end-to-end public run tests (sync + stream modes, version pinning, input validation)
- `backend/tests/test_schema_validation.py` — validation helper tests

**Modified:**
- `backend/requirements.txt` — add `bcrypt==4.2.1`, `jsonschema==4.23.0`
- `backend/app/main.py` — register `api_keys` + `public_runs` routers
- `backend/app/seed.py` — seed a demo dev API key so the UI can be tested immediately
- `backend/tests/conftest.py` — add `api_key` to the model imports line

### Frontend

**New:**
- `frontend/src/components/ApiKeyList/index.tsx` — top-level API Keys page
- `frontend/src/components/ApiKeyList/ApiKeyFormModal.tsx` — new-key form (name + scope multi-select)
- `frontend/src/components/ApiKeyList/RevealKeyModal.tsx` — show-once plaintext reveal screen
- `frontend/src/components/GraphDetail/KeysTab.tsx` — filtered-by-graph keys list with shortcut to create scoped

**Modified:**
- `frontend/src/types/index.ts` — `ApiKey`, `ApiKeyCreate`, `ApiKeyCreated` types
- `frontend/src/api/client.ts` — `listApiKeys`, `createApiKey`, `revokeApiKey`, `deleteApiKey`
- `frontend/src/App.tsx` — add `"api-keys"` to the `View` union + header tab + route component
- `frontend/src/components/GraphDetail/index.tsx` — enable **Keys** tab and render `KeysTab`

---

## Task 1: Add backend dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append two pinned deps**

Add these lines at the bottom of `backend/requirements.txt`:
```
bcrypt==4.2.1
jsonschema==4.23.0
```

- [ ] **Step 2: Install inside the backend container**

```bash
docker compose exec backend pip install bcrypt==4.2.1 jsonschema==4.23.0
```
Expected: installation completes without errors.

- [ ] **Step 3: Verify imports**

```bash
docker compose exec -T backend python -c "import bcrypt, jsonschema; print(bcrypt.__version__, jsonschema.__version__)"
```
Expected: `4.2.1 4.23.0`.

- [ ] **Step 4: Run the existing test suite as a baseline**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 43 passed (Plan B baseline).

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(deps): add bcrypt and jsonschema for Plan C"
```

---

## Task 2: Alembic migration for `api_keys`

**Files:**
- Create: `backend/alembic/versions/d5e6f7a8b9c0_api_keys.py`

- [ ] **Step 1: Write the migration file**

```python
"""api_keys table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('key_prefix', sa.String(length=24), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False),
        sa.Column('key_last4', sa.String(length=4), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_keys_key_prefix', 'api_keys', ['key_prefix'])
    op.create_index('ix_api_keys_org_id', 'api_keys', ['org_id'])


def downgrade() -> None:
    op.drop_index('ix_api_keys_org_id', table_name='api_keys')
    op.drop_index('ix_api_keys_key_prefix', table_name='api_keys')
    op.drop_table('api_keys')
```

Note: `scopes` is a JSON array — either `["*"]` for full access or a list of graph UUID strings. We could use a dedicated `api_key_scopes` child table for a fully normalized approach, but a JSON array is sufficient for MVP and matches the show-once / opaque-bag pattern of Stripe-style keys.

- [ ] **Step 2: Apply the migration**

```bash
docker compose exec backend alembic upgrade head
```
Expected: `Running upgrade c4d5e6f7a8b9 -> d5e6f7a8b9c0, api_keys table`.

- [ ] **Step 3: Verify the table**

```bash
docker compose exec -T postgres psql -U agent -d agent_platform -c "\d api_keys"
```
Expected: table with 11 columns, 2 indexes, 2 foreign keys.

- [ ] **Step 4: Smoke tests still pass**

```bash
docker compose exec -T backend pytest tests/test_smoke.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/d5e6f7a8b9c0_api_keys.py
git commit -m "feat(db): api_keys table for Plan C authentication"
```

---

## Task 3: `ApiKey` ORM model

**Files:**
- Create: `backend/app/models/api_key.py`
- Modify: `backend/tests/conftest.py` (add `api_key` to model imports)

- [ ] **Step 1: Write the model**

```python
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
```

- [ ] **Step 2: Register in conftest.py**

Open `backend/tests/conftest.py`. Find the model imports line:
```python
from app.models import agent, graph, mcp_server, run, user  # noqa: E402, F401
```
Change to:
```python
from app.models import agent, api_key, graph, mcp_server, run, user  # noqa: E402, F401
```

- [ ] **Step 3: Verify imports and smoke tests**

```bash
docker compose exec -T backend python -c "from app.models.api_key import ApiKey; print('ok')"
docker compose exec -T backend pytest tests/test_smoke.py -v
```
Expected: `ok`, 2 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/api_key.py backend/tests/conftest.py
git commit -m "feat(models): ApiKey ORM model with prefix + hash pattern"
```

---

## Task 4: Pydantic schemas for api keys

**Files:**
- Create: `backend/app/schemas/api_key.py`

- [ ] **Step 1: Write the schemas**

```python
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
```

- [ ] **Step 2: Verify import**

```bash
docker compose exec -T backend python -c "from app.schemas.api_key import ApiKeyCreate, ApiKeyOut, ApiKeyCreatedOut; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/api_key.py
git commit -m "feat(schemas): ApiKey create/out schemas with show-once plaintext"
```

---

## Task 5: API key service — generate, hash, verify (TDD)

**Files:**
- Create: `backend/app/services/api_keys.py`
- Create: `backend/tests/test_api_key_service.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_api_key_service.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.api_keys'` — 0 tests collected.

- [ ] **Step 3: Write the service**

Create `backend/app/services/api_keys.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect 6 passing**

```bash
docker compose exec -T backend pytest tests/test_api_key_service.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 49 passed (43 baseline + 6 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/api_keys.py backend/tests/test_api_key_service.py
git commit -m "feat(services): api_keys service — generate, hash, verify"
```

---

## Task 6: Management endpoints — list / create / revoke / delete (TDD)

**Files:**
- Create: `backend/app/routers/api_keys.py`
- Create: `backend/tests/test_api_keys_api.py`
- Modify: `backend/app/main.py` (register the router)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_keys_api.py`:

```python
"""Tests for /api/v1/api-keys management endpoints."""

import uuid

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.api_key import ApiKey
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    await db_session.flush()


async def test_create_key_returns_plaintext_once(client, db_session):
    await _seed(db_session)

    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "CI pipeline", "scopes": ["*"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "CI pipeline"
    assert body["scopes"] == ["*"]
    assert body["key"].startswith("ap_live_")  # plaintext shown once
    assert "key_prefix" in body
    assert body["key_prefix"] == body["key"][:16]
    assert body["key_last4"] == body["key"][-4:]
    assert body["revoked_at"] is None
    assert "id" in body


async def test_list_keys_never_returns_plaintext(client, db_session):
    await _seed(db_session)
    await client.post("/api/v1/api-keys", json={"name": "k1", "scopes": ["*"]})
    await client.post("/api/v1/api-keys", json={"name": "k2", "scopes": ["*"]})

    r = await client.get("/api/v1/api-keys")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    for k in body:
        assert "key" not in k  # plaintext NEVER in list response
        assert "key_hash" not in k  # hash also never exposed
        assert k["key_prefix"].startswith("ap_live_")
        assert len(k["key_last4"]) == 4


async def test_list_keys_ordered_newest_first(client, db_session):
    await _seed(db_session)
    r1 = await client.post("/api/v1/api-keys", json={"name": "first", "scopes": ["*"]})
    r2 = await client.post("/api/v1/api-keys", json={"name": "second", "scopes": ["*"]})

    r = await client.get("/api/v1/api-keys")
    body = r.json()
    # Newest first
    assert body[0]["name"] == "second"
    assert body[1]["name"] == "first"


async def test_create_key_with_graph_scope(client, db_session):
    await _seed(db_session)
    g = Graph(id=uuid.uuid4(), name="G", slug="g",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add(g)
    await db_session.flush()

    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "graph-scoped", "scopes": [str(g.id)]},
    )
    assert r.status_code == 201
    assert r.json()["scopes"] == [str(g.id)]


async def test_revoke_key(client, db_session):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/api-keys",
        json={"name": "to revoke", "scopes": ["*"]},
    )
    key_id = created.json()["id"]

    r = await client.post(f"/api/v1/api-keys/{key_id}/revoke")
    assert r.status_code == 200
    body = r.json()
    assert body["revoked_at"] is not None
    assert "key" not in body


async def test_delete_key(client, db_session):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/api-keys",
        json={"name": "to delete", "scopes": ["*"]},
    )
    key_id = created.json()["id"]

    r = await client.delete(f"/api/v1/api-keys/{key_id}")
    assert r.status_code == 204

    r2 = await client.get("/api/v1/api-keys")
    assert all(k["id"] != key_id for k in r2.json())


async def test_create_key_name_required(client, db_session):
    await _seed(db_session)
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "", "scopes": ["*"]},
    )
    assert r.status_code == 422


async def test_create_key_scopes_required(client, db_session):
    await _seed(db_session)
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "k", "scopes": []},
    )
    assert r.status_code == 422


async def test_revoke_missing_key_404(client, db_session):
    await _seed(db_session)
    r = await client.post(f"/api/v1/api-keys/{uuid.uuid4()}/revoke")
    assert r.status_code == 404


async def test_delete_missing_key_404(client, db_session):
    await _seed(db_session)
    r = await client.delete(f"/api/v1/api-keys/{uuid.uuid4()}")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_api_keys_api.py -v
```
Expected: 10 failures (endpoints don't exist).

- [ ] **Step 3: Write the router**

Create `backend/app/routers/api_keys.py`:

```python
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
```

- [ ] **Step 4: Register the router in main.py**

In `backend/app/main.py`, find:
```python
from app.routers import agents, execution, graphs, mcp_servers, runs
```
Change to:
```python
from app.routers import agents, api_keys, execution, graphs, mcp_servers, runs
```

Find the block of `app.include_router(...)` calls:
```python
app.include_router(graphs.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(mcp_servers.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
```

Append:
```python
app.include_router(api_keys.router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests — expect passing**

```bash
docker compose exec -T backend pytest tests/test_api_keys_api.py -v
```
Expected: 10 passed.

- [ ] **Step 6: Full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 59 passed (49 + 10 new).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/api_keys.py backend/app/main.py backend/tests/test_api_keys_api.py
git commit -m "feat(api): /api/v1/api-keys list, create, revoke, delete"
```

---

## Task 7: Schema validation helper (TDD)

**Files:**
- Create: `backend/app/services/schema_validation.py`
- Create: `backend/tests/test_schema_validation.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_schema_validation.py`:

```python
"""Unit tests for the schema validation helper."""

import pytest

from app.services.schema_validation import (
    SchemaValidationError,
    validate_against_schema,
)


def test_valid_payload_passes():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    # Should not raise
    validate_against_schema({"name": "Alice", "age": 30}, schema)


def test_missing_required_field_raises_with_field_path():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_against_schema({}, schema)
    err = exc_info.value
    assert "name" in err.message
    assert err.field == "" or err.field == "/"  # root-level error


def test_wrong_type_raises_with_field_path():
    schema = {
        "type": "object",
        "properties": {"age": {"type": "integer"}},
    }
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_against_schema({"age": "thirty"}, schema)
    assert exc_info.value.field.endswith("age") or "age" in exc_info.value.message


def test_empty_schema_accepts_anything():
    validate_against_schema({"random": "data"}, {})
    validate_against_schema({}, {})


def test_none_schema_accepts_anything():
    validate_against_schema({"anything": 1}, None)


def test_enum_violation_caught():
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["a", "b", "c"]},
        },
    }
    with pytest.raises(SchemaValidationError):
        validate_against_schema({"status": "d"}, schema)
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_schema_validation.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the helper**

Create `backend/app/services/schema_validation.py`:

```python
"""
Thin wrapper around jsonschema to raise a typed error we can translate
to a 422 response on public run endpoints.

Accepts None or empty-dict schemas as "no validation" (pass everything through),
which keeps legacy graphs without input_schema working.
"""

from __future__ import annotations

import jsonschema
from jsonschema import Draft202012Validator


class SchemaValidationError(ValueError):
    """Raised when a payload fails validation against a JSON Schema."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def validate_against_schema(
    payload: dict,
    schema: dict | None,
) -> None:
    """
    Validate payload against schema. Raises SchemaValidationError on the first
    failure. Returns None on success. Treats None or empty schema as a pass.
    """
    if not schema:
        return

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if not errors:
        return

    first = errors[0]
    # Turn a jsonschema path like deque(['user', 'name']) into "/user/name"
    field_path = "/" + "/".join(str(p) for p in first.absolute_path)
    if field_path == "/":
        field_path = ""
    raise SchemaValidationError(
        message=f"{field_path or 'request body'}: {first.message}",
        field=field_path,
    )
```

- [ ] **Step 4: Run tests**

```bash
docker compose exec -T backend pytest tests/test_schema_validation.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/schema_validation.py backend/tests/test_schema_validation.py
git commit -m "feat(services): schema_validation helper for public endpoint validation"
```

---

## Task 8: Auth dependency + scope helper (TDD)

**Files:**
- Create: `backend/app/security/__init__.py` (empty)
- Create: `backend/app/security/auth.py`
- Modify: `backend/app/models/api_key.py` (no changes — already done in Task 3)

This task creates the auth dependency but doesn't wire it into any router yet. Task 9 will use it from the public runs router.

- [ ] **Step 1: Write the security package marker**

```bash
mkdir -p backend/app/security
touch backend/app/security/__init__.py
```

- [ ] **Step 2: Write the auth dependency**

Create `backend/app/security/auth.py`:

```python
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
```

- [ ] **Step 3: Commit (no tests yet — they come with Task 9 where the dep is wired up)**

```bash
git add backend/app/security/
git commit -m "feat(security): authenticate_api_key dependency + check_graph_scope"
```

---

## Task 9: Public run endpoints (sync + stream) with auth (TDD)

**Files:**
- Create: `backend/app/routers/public_runs.py`
- Create: `backend/tests/test_public_runs_auth.py`
- Create: `backend/tests/test_public_runs_execution.py`
- Modify: `backend/app/main.py` (register public_runs router with NO /api/v1 prefix)

- [ ] **Step 1: Write the auth failing tests**

Create `backend/tests/test_public_runs_auth.py`:

```python
"""Auth dependency tests — 401/404 edge cases on public run endpoints."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed_graph(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Acme", slug="acme"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="test-graph",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "echo", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g)
    await db_session.flush()
    return g


async def _create_key(client, name: str, scopes: list[str]) -> dict:
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "scopes": scopes},
    )
    assert r.status_code == 201
    return r.json()


async def test_missing_auth_header_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
    )
    assert r.status_code == 401


async def test_malformed_auth_header_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": "NotBearer xyz"},
    )
    assert r.status_code == 401


async def test_invalid_key_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": "Bearer ap_live_notarealkey00000000000000"},
    )
    assert r.status_code == 401


async def test_revoked_key_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    key = await _create_key(client, "revoke-me", ["*"])
    plaintext = key["key"]

    revoke_r = await client.post(f"/api/v1/api-keys/{key['id']}/revoke")
    assert revoke_r.status_code == 200

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert r.status_code == 401


async def test_wildcard_scope_allows_any_graph(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "node_end", "node": "echo", "data": {"message_text": "ok"}}
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    key = await _create_key(client, "wildcard", ["*"])

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert r.status_code == 200


async def test_specific_scope_allows_only_that_graph(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    # Create a second graph we will NOT include in scope
    g_other = Graph(
        id=uuid.uuid4(),
        name="Other",
        slug="other",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "n", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "n", "condition": None},
                {"from": "n", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g_other)
    await db_session.flush()

    key = await _create_key(client, "scoped", [str(g.id)])

    # In-scope: 200 (or at least not 401/404)
    ok = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert ok.status_code == 200

    # Out-of-scope: 404 (deliberately not 403 — avoids enumeration)
    not_ok = await client.post(
        f"/v1/run/acme/{g_other.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert not_ok.status_code == 404


async def test_missing_graph_slug_returns_404(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    await _seed_graph(db_session)
    key = await _create_key(client, "k", ["*"])

    r = await client.post(
        "/v1/run/acme/does-not-exist",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert r.status_code == 404


async def test_missing_org_slug_returns_404(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    key = await _create_key(client, "k", ["*"])

    r = await client.post(
        f"/v1/run/wrong-org/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Write the execution failing tests**

Create `backend/tests/test_public_runs_execution.py`:

```python
"""End-to-end tests for POST /v1/run/{org}/{slug} — sync + stream + validation."""

import json
import uuid

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.run import Run
from app.models.user import Org, User


async def _seed_graph_with_schema(db_session, input_schema=None):
    db_session.add(Org(id=DEV_ORG_ID, name="Acme", slug="acme"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="echo",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "echo", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
        input_schema=input_schema,
    )
    db_session.add(g)
    await db_session.flush()
    return g


async def _stub_stream(monkeypatch, events=None):
    if events is None:
        events = [
            {"event": "node_start", "node": "echo", "data": None},
            {"event": "node_end", "node": "echo", "data": {"message_text": "ok"}},
            {"event": "done", "node": None, "data": {}},
        ]

    async def fake_stream(*a, **kw):
        for evt in events:
            yield evt

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)


async def _create_key(client) -> str:
    r = await client.post("/api/v1/api-keys", json={"name": "k", "scopes": ["*"]})
    return r.json()["key"]


async def test_public_sync_mode_returns_json(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {"hello": "world"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body
    assert body["status"] == "succeeded"
    # Sync mode returns accumulated output (message_text from the last node_end)
    assert "output" in body


async def test_public_sync_mode_persists_run_with_trigger(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {"hello": "world"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    run_id = uuid.UUID(r.json()["run_id"])

    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.trigger_source == "api_sync"
    assert run.status == "succeeded"


async def test_public_stream_mode_returns_sse(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}?mode=stream",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    # SSE: body is a series of "data: {json}\n\n" blocks
    events = []
    for line in r.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    assert events[0]["event"] == "run_started"
    assert any(e["event"] == "done" for e in events)


async def test_public_stream_mode_persists_with_stream_trigger(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}?mode=stream",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    # Pull run_id from the first SSE event
    for line in r.text.split("\n"):
        if line.startswith("data: "):
            evt = json.loads(line[6:])
            if evt["event"] == "run_started":
                run_id = uuid.UUID(evt["data"]["run_id"])
                break

    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.trigger_source == "api_stream"


async def test_input_validation_failure_returns_422(client, db_session, monkeypatch):
    schema = {
        "type": "object",
        "required": ["title"],
        "properties": {"title": {"type": "string"}},
    }
    g = await _seed_graph_with_schema(db_session, input_schema=schema)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    # Missing required "title"
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 422
    assert "title" in r.json()["error"]


async def test_version_pinning_via_at_suffix(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)

    # Publish v1
    pub = await client.post(f"/api/v1/graphs/{g.id}/publish", json={})
    assert pub.status_code == 201

    key = await _create_key(client)

    # Pin via @v1 suffix in the slug
    r = await client.post(
        f"/v1/run/acme/{g.slug}@v1",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    run_id = uuid.UUID(r.json()["run_id"])

    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.graph_version_id is not None


async def test_version_pin_to_missing_version_returns_404(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}@v99",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 404
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_public_runs_auth.py tests/test_public_runs_execution.py -v
```
Expected: 15+ failures (endpoint missing).

- [ ] **Step 4: Write the public runs router**

Create `backend/app/routers/public_runs.py`:

```python
"""
Public run endpoints at /v1/run/{org}/{slug}.

Separate from /api/v1/* (management) so the public surface can evolve its own
versioning without breaking the management API.

Modes:
  - Default: sync — buffers SSE stream, returns {run_id, status, output} JSON
  - ?mode=stream: SSE passthrough — same event shape as the editor test endpoint

Version pinning: the slug path parameter accepts either "my-slug" or
"my-slug@v3". The @vN suffix is parsed out before graph lookup.

Auth: Authorization: Bearer ap_live_... handled by authenticate_api_key dep.
Scope: check_graph_scope raises 404 when the key lacks access.

Input validation: body.input is validated against graph.input_schema via
jsonschema. 422 on mismatch with {"error": "/path: reason"}.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.engine.persistence import run_graph
from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.graph import Graph, GraphVersion
from app.models.mcp_server import MCPServer
from app.models.user import Org
from app.schemas.execution import RunRequest
from app.security.auth import authenticate_api_key, check_graph_scope
from app.services.schema_validation import SchemaValidationError, validate_against_schema

router = APIRouter(prefix="/v1/run", tags=["public-runs"])


def _parse_slug_with_version(raw: str) -> tuple[str, int | None]:
    """
    Split 'my-slug@v3' into ('my-slug', 3). If no @vN suffix, version is None.
    """
    if "@v" in raw:
        base, _, v_str = raw.rpartition("@v")
        try:
            return base, int(v_str)
        except ValueError:
            return raw, None
    return raw, None


async def _load_definition(
    db: AsyncSession,
    graph: Graph,
    version: int | None,
) -> tuple[dict, uuid.UUID | None]:
    """Resolve the definition to execute, returning (definition, version_id | None)."""
    if version is None:
        return graph.definition_json, None
    v_result = await db.execute(
        select(GraphVersion).where(
            GraphVersion.graph_id == graph.id,
            GraphVersion.version == version,
        )
    )
    gv = v_result.scalar_one_or_none()
    if not gv:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return gv.definition_json, gv.id


async def _collect_refs(db: AsyncSession, definition: dict) -> tuple[dict, dict]:
    """Load MCP server + agent rows referenced in the definition."""
    mcp_server_ids: set[str] = set()
    agent_ids: set[str] = set()
    for node in definition.get("nodes", []):
        cfg = node.get("config") or {}
        if sid := cfg.get("mcp_server_id"):
            mcp_server_ids.add(str(sid))
        for sid in cfg.get("mcp_server_ids") or []:
            mcp_server_ids.add(str(sid))
        if aid := cfg.get("agent_id"):
            agent_ids.add(str(aid))

    mcp_servers: dict[str, dict] = {}
    if mcp_server_ids:
        uuids = [uuid.UUID(s) for s in mcp_server_ids]
        result = await db.execute(select(MCPServer).where(MCPServer.id.in_(uuids)))
        for srv in result.scalars().all():
            mcp_servers[str(srv.id)] = {
                "transport": srv.transport,
                "url": srv.url,
                "command": srv.command,
                "args": srv.args,
                "env_vars": srv.env_vars,
            }

    agents: dict[str, dict] = {}
    if agent_ids:
        uuids = [uuid.UUID(s) for s in agent_ids]
        result = await db.execute(select(Agent).where(Agent.id.in_(uuids)))
        for ag in result.scalars().all():
            agents[str(ag.id)] = {
                "url": ag.url,
                "agent_type": ag.agent_type,
                "agent_card_json": ag.agent_card_json,
            }
    return mcp_servers, agents


@router.post("/{org_slug}/{graph_slug}")
async def public_run(
    org_slug: str,
    graph_slug: str,
    body: RunRequest,
    mode: str = Query(default="sync", pattern="^(sync|stream)$"),
    api_key: ApiKey = Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_db),
):
    # 1. Parse optional @vN suffix from the slug
    slug, version = _parse_slug_with_version(graph_slug)

    # 2. Resolve the org
    org_result = await db.execute(select(Org).where(Org.slug == org_slug))
    org = org_result.scalar_one_or_none()
    if not org or org.id != api_key.org_id:
        raise HTTPException(status_code=404, detail="Graph not found")

    # 3. Resolve the graph
    graph_result = await db.execute(
        select(Graph).where(Graph.org_id == org.id, Graph.slug == slug)
    )
    graph = graph_result.scalar_one_or_none()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # 4. Scope check — raises 404 on mismatch to avoid enumeration
    check_graph_scope(api_key, graph.id)

    # 5. Input validation against input_schema (if present)
    try:
        validate_against_schema(body.input, graph.input_schema)
    except SchemaValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message)

    # 6. Load pinned version if @vN was given
    definition, graph_version_id = await _load_definition(db, graph, version)
    if not definition or not definition.get("nodes"):
        raise HTTPException(status_code=422, detail="Graph has no definition")

    # 7. Collect referenced agents / mcp servers
    mcp_servers, agents = await _collect_refs(db, definition)

    trigger_source = "api_stream" if mode == "stream" else "api_sync"

    if mode == "stream":
        async def event_stream():
            async for event in run_graph(
                db=db,
                graph=graph,
                graph_version_id=graph_version_id,
                trigger_source=trigger_source,
                run_input=body.input,
                mcp_servers=mcp_servers,
                agents=agents,
                definition=definition,
            ):
                yield f"data: {json.dumps(event, default=str)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Sync mode: consume the generator fully, buffer the final output
    run_id: str | None = None
    final_output: dict | None = None
    final_error: str | None = None
    async for event in run_graph(
        db=db,
        graph=graph,
        graph_version_id=graph_version_id,
        trigger_source=trigger_source,
        run_input=body.input,
        mcp_servers=mcp_servers,
        agents=agents,
        definition=definition,
    ):
        kind = event.get("event")
        if kind == "run_started":
            run_id = event.get("data", {}).get("run_id")
        elif kind == "node_end":
            data = event.get("data") or {}
            if isinstance(data, dict):
                final_output = {k: v for k, v in data.items() if k != "last_usage"}
        elif kind == "error":
            final_error = str(event.get("data") or "Unknown error")

    if final_error:
        return {
            "run_id": run_id,
            "status": "failed",
            "error": final_error,
        }
    return {
        "run_id": run_id,
        "status": "succeeded",
        "output": final_output,
    }
```

- [ ] **Step 5: Register the router in main.py**

In `backend/app/main.py`, add `public_runs` to the imports line:
```python
from app.routers import agents, api_keys, execution, graphs, mcp_servers, public_runs, runs
```

And add the registration — note the **empty prefix** (public_runs router declares `/v1/run` in its own `prefix=`):
```python
app.include_router(graphs.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(mcp_servers.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(api_keys.router, prefix="/api/v1")
app.include_router(public_runs.router)  # no prefix — exposes /v1/run/...
```

- [ ] **Step 6: Run tests — expect passing**

```bash
docker compose exec -T backend pytest tests/test_public_runs_auth.py tests/test_public_runs_execution.py -v
```
Expected: 15 passed (8 auth + 7 execution).

- [ ] **Step 7: Full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 80 passed (59 previous + 15 public run + 6 schema validation — wait, the schema validation tests were run in Task 7 and added 6, so actual count is 59 + 15 = 74 plus the 6 added in Task 7 is already in 59 + 6 = 65, then Task 9 adds 15 → 80).

Recalc: Task 5 added 10 (total 59). Task 7 added 6 (total 65). Task 9 adds 15 (total 80). Expected: 80 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/public_runs.py backend/app/main.py backend/tests/test_public_runs_auth.py backend/tests/test_public_runs_execution.py
git commit -m "feat(api): /v1/run/{org}/{slug} public endpoints with auth + validation"
```

---

## Task 10: Seed a demo API key

**Files:**
- Modify: `backend/app/seed.py`

A demo key means the UI shows something immediately after `docker compose up` and we can curl against the public endpoint without going through the creation flow first.

- [ ] **Step 1: Add seed constants and demo key upsert**

Open `backend/app/seed.py`. Find the seed-id constants block near the top:
```python
SEED_MCP_SERVER_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
SEED_A2A_AGENT_ID  = uuid.UUID("00000000-0000-0000-0000-000000000011")
SEED_GRAPH_ID      = uuid.UUID("00000000-0000-0000-0000-000000000020")
```

Add:
```python
SEED_API_KEY_ID    = uuid.UUID("00000000-0000-0000-0000-000000000030")
# The plaintext for the seed key is deterministic so curl examples in docs
# and the readme can reference it. This is ONLY safe because it's a local-dev
# key seeded in DEBUG mode. Production deployments never run the seed.
SEED_API_KEY_PLAINTEXT = "ap_live_demoseedkey0000000000000000000000"
```

- [ ] **Step 2: Add an upsert helper for the seed key**

After the existing `_upsert_agent` or `_upsert_graph` function, add:

```python
async def _upsert_api_key(db, stats: SeedStats) -> None:
    from app.models.api_key import ApiKey
    from app.services.api_keys import hash_key, split_prefix

    key = await db.get(ApiKey, SEED_API_KEY_ID)
    if not key:
        db.add(ApiKey(
            id=SEED_API_KEY_ID,
            org_id=DEV_ORG_ID,
            name="Demo dev key",
            key_prefix=split_prefix(SEED_API_KEY_PLAINTEXT),
            key_hash=hash_key(SEED_API_KEY_PLAINTEXT),
            key_last4=SEED_API_KEY_PLAINTEXT[-4:],
            scopes=["*"],
            created_by=DEV_USER_ID,
        ))
        stats["inserted"] += 1
        log.info("seeded_demo_api_key")
    else:
        # Don't re-hash or mutate the existing key — it's already correct
        stats["unchanged"] += 1
```

- [ ] **Step 3: Wire the helper into `seed()`**

Find the main `seed()` function body — it already calls `_upsert_org`, `_upsert_user`, `_upsert_mcp_server`, `_upsert_agent`, `_upsert_graph`, `_ensure_seed_graph_published`. Add the key upsert after `_ensure_seed_graph_published`:

```python
        await _upsert_graph(db, stats)
        await _ensure_seed_graph_published(db, stats)
        await _upsert_api_key(db, stats)

        await db.commit()
```

- [ ] **Step 4: Restart the backend and verify**

```bash
docker compose restart backend
sleep 3
docker compose logs backend --tail 30 | grep -E "seeded_demo_api_key|seed_complete"
```
Expected: log lines include `seeded_demo_api_key` and `seed_complete`.

Verify the key appears in the list:
```bash
curl -s http://localhost:8000/api/v1/api-keys | jq '.[0] | {name, scopes, key_prefix}'
```
Expected: JSON object with `name: "Demo dev key"`, `scopes: ["*"]`, and a `key_prefix` starting with `ap_live_`.

Verify the demo key actually works against the public endpoint:
```bash
curl -s -X POST "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{"title":"Demo run","description":"test","affected_services":["payments"],"proposed_window":"now"}}' \
  | head -20
```
Expected: either a sync JSON response (if no error) or a 422 with input validation error. NOT a 401/404 — those would mean auth isn't working.

Note: the org slug is `demo` not `acme` because the existing seed's org.slug is `"demo"` (set in Plan A task 9).

- [ ] **Step 5: Run full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 80 passed (no change — seed isn't touched by SQLite test fixtures).

- [ ] **Step 6: Commit**

```bash
git add backend/app/seed.py
git commit -m "feat(seed): demo dev API key for quick testing"
```

---

## Task 11: Frontend types and API client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add ApiKey types**

Append to `frontend/src/types/index.ts`:

```typescript
export interface ApiKey {
  id: string;
  org_id: string;
  name: string;
  key_prefix: string;
  key_last4: string;
  scopes: string[]; // ["*"] or list of graph UUIDs
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreate {
  name: string;
  scopes: string[];
}

export interface ApiKeyCreated extends ApiKey {
  key: string; // plaintext, shown ONCE
}
```

- [ ] **Step 2: Update API client imports and add functions**

Open `frontend/src/api/client.ts`. Add the new types to the existing import block:

```typescript
import type {
  Agent,
  AgentCreate,
  AgentUpdate,
  ApiKey,
  ApiKeyCreate,
  ApiKeyCreated,
  Graph,
  GraphPublishBody,
  GraphSummary,
  GraphVersion,
  GraphVersionSummary,
  MCPServer,
  MCPServerCreate,
  MCPServerUpdate,
  MCPTool,
  Run,
  RunSummary,
  TestExample,
  TestExampleCreate,
  Usage,
} from "../types";
```

Append these functions:

```typescript
// API Keys
export const listApiKeys = (): Promise<ApiKey[]> =>
  api.get("/api-keys").then((r) => r.data);

export const createApiKey = (body: ApiKeyCreate): Promise<ApiKeyCreated> =>
  api.post("/api-keys", body).then((r) => r.data);

export const revokeApiKey = (id: string): Promise<ApiKey> =>
  api.post(`/api-keys/${id}/revoke`).then((r) => r.data);

export const deleteApiKey = (id: string): Promise<void> =>
  api.delete(`/api-keys/${id}`).then(() => undefined);
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(frontend): types and API client for API keys"
```

---

## Task 12: `ApiKeyFormModal` and `RevealKeyModal` components

**Files:**
- Create: `frontend/src/components/ApiKeyList/ApiKeyFormModal.tsx`
- Create: `frontend/src/components/ApiKeyList/RevealKeyModal.tsx`

These two exist as separate files to keep responsibilities clear: the form collects input, the reveal shows the show-once plaintext after a successful create.

- [ ] **Step 1: Write `ApiKeyFormModal.tsx`**

```typescript
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createApiKey, listGraphs } from "../../api/client";
import { Modal } from "../shared/Modal";
import type { ApiKeyCreated, ApiKeyCreate } from "../../types";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Optional: if provided, pre-select this graph in the scope and lock wildcard off */
  preScopedGraphId?: string;
  /** Called with the plaintext-bearing response when the key is created */
  onCreated: (created: ApiKeyCreated) => void;
}

export function ApiKeyFormModal({ open, onClose, preScopedGraphId, onCreated }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [wildcard, setWildcard] = useState(!preScopedGraphId);
  const [selectedGraphIds, setSelectedGraphIds] = useState<string[]>(
    preScopedGraphId ? [preScopedGraphId] : []
  );
  const [error, setError] = useState<string | null>(null);

  const { data: graphs = [] } = useQuery({
    queryKey: ["graphs"],
    queryFn: listGraphs,
    enabled: open,
  });

  useEffect(() => {
    if (open) {
      setName("");
      setWildcard(!preScopedGraphId);
      setSelectedGraphIds(preScopedGraphId ? [preScopedGraphId] : []);
      setError(null);
    }
  }, [open, preScopedGraphId]);

  const createMut = useMutation({
    mutationFn: (body: ApiKeyCreate) => createApiKey(body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      onCreated(created);
    },
    onError: (err: unknown) => {
      const resp = (err as { response?: { data?: { error?: string; detail?: string } } }).response;
      setError(resp?.data?.error ?? resp?.data?.detail ?? "Create failed");
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    const scopes = wildcard ? ["*"] : selectedGraphIds;
    if (!wildcard && scopes.length === 0) {
      setError("Select at least one graph or choose 'All graphs'");
      return;
    }
    createMut.mutate({ name: name.trim(), scopes });
  };

  const toggleGraph = (id: string) => {
    setSelectedGraphIds((prev) =>
      prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]
    );
  };

  return (
    <Modal
      open={open}
      title="New API Key"
      onClose={onClose}
      locked={createMut.isPending}
      maxWidth={520}
    >
      <form onSubmit={submit}>
        <div style={styles.field}>
          <label style={styles.label}>Name</label>
          <input
            style={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={createMut.isPending}
            placeholder="e.g. Staging pipeline"
            autoFocus
          />
        </div>

        <div style={styles.field}>
          <label style={styles.label}>Scope</label>
          <label style={styles.radioRow}>
            <input
              type="radio"
              checked={wildcard}
              onChange={() => setWildcard(true)}
              disabled={createMut.isPending || Boolean(preScopedGraphId)}
            />
            <span style={{ fontSize: 13 }}>All graphs (*)</span>
          </label>
          <label style={styles.radioRow}>
            <input
              type="radio"
              checked={!wildcard}
              onChange={() => setWildcard(false)}
              disabled={createMut.isPending}
            />
            <span style={{ fontSize: 13 }}>Specific graphs</span>
          </label>
          {!wildcard && (
            <div style={styles.graphList}>
              {graphs.length === 0 && (
                <div style={{ color: "#9ca3af", fontSize: 12 }}>No graphs to pick.</div>
              )}
              {graphs.map((g) => (
                <label key={g.id} style={styles.graphRow}>
                  <input
                    type="checkbox"
                    checked={selectedGraphIds.includes(g.id)}
                    onChange={() => toggleGraph(g.id)}
                    disabled={createMut.isPending}
                  />
                  <span style={{ fontSize: 13 }}>{g.name}</span>
                  {g.slug && (
                    <code style={styles.slug}>{g.slug}</code>
                  )}
                </label>
              ))}
            </div>
          )}
          {preScopedGraphId && !wildcard && (
            <div style={styles.hint}>Pre-selected for the current graph.</div>
          )}
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.actions}>
          <button
            type="button"
            style={styles.cancelBtn}
            onClick={onClose}
            disabled={createMut.isPending}
          >
            Cancel
          </button>
          <button
            type="submit"
            style={styles.submitBtn}
            disabled={createMut.isPending}
          >
            {createMut.isPending ? "Creating…" : "Create key"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  field: { marginBottom: 14 },
  label: {
    display: "block",
    fontSize: 11,
    fontWeight: 700,
    color: "#374151",
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    boxSizing: "border-box",
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
    cursor: "pointer",
  },
  graphList: {
    marginTop: 6,
    padding: 8,
    border: "1px solid #e5e7eb",
    borderRadius: 5,
    maxHeight: 180,
    overflowY: "auto",
  },
  graphRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "3px 0",
    cursor: "pointer",
  },
  slug: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#6b7280",
    marginLeft: "auto",
  },
  hint: { fontSize: 11, color: "#6b7280", marginTop: 4 },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "8px 12px",
    borderRadius: 5,
    fontSize: 12,
    marginBottom: 12,
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
    marginTop: 6,
  },
  cancelBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  },
  submitBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
  },
};
```

- [ ] **Step 2: Write `RevealKeyModal.tsx`**

```typescript
import { useState } from "react";
import { Modal } from "../shared/Modal";
import type { ApiKeyCreated } from "../../types";

interface Props {
  open: boolean;
  created: ApiKeyCreated | null;
  onClose: () => void;
}

export function RevealKeyModal({ open, created, onClose }: Props) {
  const [copied, setCopied] = useState(false);

  if (!created) return null;

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API may not be available in insecure contexts
    }
  };

  return (
    <Modal
      open={open}
      title="Save your API key now"
      onClose={onClose}
      maxWidth={560}
    >
      <div style={styles.warn}>
        ⚠ <strong>You won't see this key again.</strong> Copy it now and store it
        somewhere safe. If you lose it, you'll need to create a new one.
      </div>

      <div style={styles.meta}>
        <div style={styles.metaRow}>
          <span style={styles.metaLabel}>Name</span>
          <span>{created.name}</span>
        </div>
        <div style={styles.metaRow}>
          <span style={styles.metaLabel}>Scope</span>
          <span>
            {created.scopes.includes("*")
              ? "All graphs"
              : `${created.scopes.length} graph${created.scopes.length === 1 ? "" : "s"}`}
          </span>
        </div>
      </div>

      <div style={styles.keyLabel}>Your API key</div>
      <div style={styles.keyBox}>
        <code style={styles.key}>{created.key}</code>
      </div>

      <div style={styles.actions}>
        <button
          style={styles.copyBtn}
          onClick={copyKey}
        >
          {copied ? "✓ Copied" : "📋 Copy key"}
        </button>
        <button style={styles.doneBtn} onClick={onClose}>
          I've saved it
        </button>
      </div>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  warn: {
    background: "#fffbeb",
    border: "1px solid #fcd34d",
    color: "#78350f",
    borderRadius: 6,
    padding: "10px 14px",
    fontSize: 13,
    marginBottom: 16,
    lineHeight: 1.5,
  },
  meta: {
    marginBottom: 14,
  },
  metaRow: {
    display: "flex",
    gap: 12,
    padding: "4px 0",
    fontSize: 13,
    color: "#111827",
    borderBottom: "1px solid #f3f4f6",
  },
  metaLabel: {
    width: 80,
    color: "#6b7280",
    fontSize: 12,
  },
  keyLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 6,
  },
  keyBox: {
    background: "#0f172a",
    borderRadius: 6,
    padding: 14,
    marginBottom: 14,
    overflowX: "auto",
  },
  key: {
    color: "#86efac",
    fontFamily: "monospace",
    fontSize: 13,
    wordBreak: "break-all",
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
  },
  copyBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  },
  doneBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
  },
};
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ApiKeyList/ApiKeyFormModal.tsx frontend/src/components/ApiKeyList/RevealKeyModal.tsx
git commit -m "feat(frontend): ApiKeyFormModal and RevealKeyModal with show-once plaintext"
```

---

## Task 13: Top-level `ApiKeyList` page

**Files:**
- Create: `frontend/src/components/ApiKeyList/index.tsx`

- [ ] **Step 1: Write the list page**

```typescript
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteApiKey, listApiKeys, revokeApiKey } from "../../api/client";
import { Modal } from "../shared/Modal";
import { ApiKeyFormModal } from "./ApiKeyFormModal";
import { RevealKeyModal } from "./RevealKeyModal";
import type { ApiKey, ApiKeyCreated } from "../../types";

interface Banner {
  kind: "success" | "warn" | "error";
  text: string;
}

export function ApiKeyList() {
  const qc = useQueryClient();
  const { data: keys = [], isLoading } = useQuery({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [reveal, setReveal] = useState<ApiKeyCreated | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ kind: "revoke" | "delete"; key: ApiKey } | null>(null);
  const [banner, setBanner] = useState<Banner | null>(null);

  const revokeMut = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      setBanner({ kind: "success", text: "Key revoked." });
      setConfirmAction(null);
    },
    onError: () => setBanner({ kind: "error", text: "Revoke failed." }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteApiKey(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      setBanner({ kind: "success", text: "Key deleted." });
      setConfirmAction(null);
    },
    onError: () => setBanner({ kind: "error", text: "Delete failed." }),
  });

  if (isLoading) return <div style={styles.container}>Loading API keys…</div>;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={{ margin: 0 }}>API Keys</h2>
        <button style={styles.newBtn} onClick={() => setFormOpen(true)}>
          + New Key
        </button>
      </div>

      <p style={styles.intro}>
        Keys authenticate calls to public run endpoints at{" "}
        <code style={styles.code}>POST /v1/run/{"{org}/{slug}"}</code>. Use{" "}
        <code style={styles.code}>Authorization: Bearer ap_live_...</code>.
      </p>

      {banner && (
        <div style={{ ...styles.banner, ...bannerStyle(banner.kind) }}>
          <span>{banner.text}</span>
          <button style={styles.bannerClose} onClick={() => setBanner(null)}>×</button>
        </div>
      )}

      {keys.length === 0 ? (
        <p style={{ color: "#6b7280" }}>
          No keys yet. Click "+ New Key" to create one.
        </p>
      ) : (
        keys.map((k) => (
          <div key={k.id} style={styles.card}>
            <div style={styles.cardBody}>
              <div style={styles.titleRow}>
                <span style={styles.keyName}>{k.name}</span>
                <ScopeBadge scopes={k.scopes} />
                {k.revoked_at && <span style={styles.revokedBadge}>REVOKED</span>}
              </div>
              <div style={styles.keyIdRow}>
                <code style={styles.prefix}>{k.key_prefix}</code>
                <span style={styles.dots}>…{k.key_last4}</span>
              </div>
              <div style={styles.meta}>
                Created {new Date(k.created_at).toLocaleDateString()}
                {" · "}
                {k.last_used_at
                  ? `last used ${new Date(k.last_used_at).toLocaleDateString()}`
                  : "never used"}
              </div>
            </div>
            <div style={styles.actions}>
              {!k.revoked_at && (
                <button
                  style={styles.btn}
                  onClick={() => setConfirmAction({ kind: "revoke", key: k })}
                >
                  Revoke
                </button>
              )}
              <button
                style={{ ...styles.btn, color: "#dc2626" }}
                onClick={() => setConfirmAction({ kind: "delete", key: k })}
              >
                Delete
              </button>
            </div>
          </div>
        ))
      )}

      <ApiKeyFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onCreated={(created) => {
          setFormOpen(false);
          setReveal(created);
        }}
      />

      <RevealKeyModal
        open={Boolean(reveal)}
        created={reveal}
        onClose={() => setReveal(null)}
      />

      <Modal
        open={Boolean(confirmAction)}
        title={confirmAction?.kind === "revoke" ? "Revoke API Key" : "Delete API Key"}
        onClose={() => setConfirmAction(null)}
        locked={revokeMut.isPending || deleteMut.isPending}
      >
        {confirmAction && (
          <>
            <div style={{ fontSize: 13, marginBottom: 12 }}>
              {confirmAction.kind === "revoke" ? (
                <>
                  Revoke <strong>{confirmAction.key.name}</strong>? It will immediately
                  stop working. Existing runs that were started with this key will
                  complete, but no new calls will be accepted.
                </>
              ) : (
                <>
                  Delete <strong>{confirmAction.key.name}</strong>? This permanently
                  removes the row. Prefer <strong>Revoke</strong> if you want to
                  keep an audit trail.
                </>
              )}
            </div>
            <div style={styles.modalActions}>
              <button
                style={styles.cancelBtn}
                onClick={() => setConfirmAction(null)}
                disabled={revokeMut.isPending || deleteMut.isPending}
              >
                Cancel
              </button>
              <button
                style={styles.dangerBtn}
                onClick={() => {
                  if (confirmAction.kind === "revoke") {
                    revokeMut.mutate(confirmAction.key.id);
                  } else {
                    deleteMut.mutate(confirmAction.key.id);
                  }
                }}
                disabled={revokeMut.isPending || deleteMut.isPending}
              >
                {revokeMut.isPending || deleteMut.isPending
                  ? "Working…"
                  : confirmAction.kind === "revoke" ? "Revoke" : "Delete"}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

function ScopeBadge({ scopes }: { scopes: string[] }) {
  const isWild = scopes.includes("*");
  return (
    <span style={{
      background: isWild ? "#fef3c7" : "#dbeafe",
      color: isWild ? "#92400e" : "#1e40af",
      border: `1px solid ${isWild ? "#fcd34d" : "#bfdbfe"}`,
      borderRadius: 4,
      padding: "1px 7px",
      fontSize: 10,
      fontWeight: 700,
    }}>
      {isWild ? "ALL GRAPHS" : `${scopes.length} SCOPE${scopes.length === 1 ? "" : "S"}`}
    </span>
  );
}

function bannerStyle(kind: Banner["kind"]): React.CSSProperties {
  switch (kind) {
    case "success": return { background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" };
    case "warn":    return { background: "#fffbeb", color: "#92400e", border: "1px solid #fcd34d" };
    case "error":   return { background: "#fef2f2", color: "#b91c1c", border: "1px solid #fca5a5" };
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: { padding: 24, maxWidth: 900, margin: "0 auto" },
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    marginBottom: 12,
  },
  newBtn: {
    background: "#2563eb", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontWeight: 600, fontSize: 13,
  },
  intro: {
    fontSize: 13,
    color: "#4b5563",
    marginBottom: 16,
    lineHeight: 1.5,
  },
  code: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#374151",
  },
  banner: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "8px 12px", borderRadius: 5, fontSize: 12, marginBottom: 12,
  },
  bannerClose: {
    background: "none", border: "none", cursor: "pointer",
    fontSize: 16, lineHeight: 1, color: "inherit", opacity: 0.7,
  },
  card: {
    border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 12,
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "#fff",
  },
  cardBody: { flex: 1, marginRight: 12 },
  titleRow: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  keyName: { fontWeight: 600, fontSize: 15, color: "#111827" },
  revokedBadge: {
    background: "#fef2f2",
    color: "#dc2626",
    border: "1px solid #fca5a5",
    borderRadius: 4,
    padding: "1px 7px",
    fontSize: 10,
    fontWeight: 700,
  },
  keyIdRow: { display: "flex", alignItems: "center", gap: 4, marginTop: 4 },
  prefix: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
    color: "#374151",
  },
  dots: { fontFamily: "monospace", fontSize: 12, color: "#9ca3af" },
  meta: { color: "#9ca3af", fontSize: 12, marginTop: 5 },
  actions: { display: "flex", gap: 6, flexShrink: 0 },
  btn: {
    background: "#f3f4f6", border: "1px solid #d1d5db",
    borderRadius: 5, padding: "5px 10px", cursor: "pointer", fontSize: 12,
  },
  modalActions: {
    display: "flex", gap: 8, justifyContent: "flex-end",
    marginTop: 14, borderTop: "1px solid #e5e7eb", paddingTop: 14,
  },
  cancelBtn: {
    background: "#f3f4f6", border: "1px solid #d1d5db",
    borderRadius: 6, padding: "8px 16px", cursor: "pointer",
    fontSize: 13, fontWeight: 600,
  },
  dangerBtn: {
    background: "#dc2626", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 20px", cursor: "pointer",
    fontSize: 13, fontWeight: 700,
  },
};
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ApiKeyList/index.tsx
git commit -m "feat(frontend): top-level ApiKeyList page with revoke/delete"
```

---

## Task 14: `KeysTab` component inside GraphDetail

**Files:**
- Create: `frontend/src/components/GraphDetail/KeysTab.tsx`

Client-side filtered view of keys that have scope over the current graph. Shortcut to create a scoped key.

- [ ] **Step 1: Write the component**

```typescript
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listApiKeys } from "../../api/client";
import { ApiKeyFormModal } from "../ApiKeyList/ApiKeyFormModal";
import { RevealKeyModal } from "../ApiKeyList/RevealKeyModal";
import type { ApiKey, ApiKeyCreated } from "../../types";

interface Props {
  graphId: string;
}

export function KeysTab({ graphId }: Props) {
  const [formOpen, setFormOpen] = useState(false);
  const [reveal, setReveal] = useState<ApiKeyCreated | null>(null);

  const { data: allKeys = [], isLoading } = useQuery({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });

  // Filter keys that have access to this graph (wildcard OR explicitly scoped)
  const filtered = allKeys.filter(
    (k) => k.scopes.includes("*") || k.scopes.includes(graphId)
  );

  if (isLoading) return <div>Loading keys…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={styles.header}>
        <div>
          <div style={styles.title}>API keys with access to this graph</div>
          <div style={styles.subtitle}>
            Shown below are all keys whose scope includes this graph (either explicitly or via <code>*</code>).
            Manage all org-wide keys on the <strong>API Keys</strong> page.
          </div>
        </div>
        <button style={styles.newBtn} onClick={() => setFormOpen(true)}>
          + New key scoped to this graph
        </button>
      </div>

      {filtered.length === 0 ? (
        <div style={styles.empty}>
          <div style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
            No keys can call this graph yet
          </div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
            Create a key scoped to this graph (or a wildcard key) to enable public API access.
          </div>
        </div>
      ) : (
        <div style={styles.tableCard}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.headRow}>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Key</th>
                <th style={styles.th}>Scope</th>
                <th style={styles.th}>Last used</th>
                <th style={styles.th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((k) => (
                <KeyRow key={k.id} keyRow={k} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ApiKeyFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        preScopedGraphId={graphId}
        onCreated={(created) => {
          setFormOpen(false);
          setReveal(created);
        }}
      />

      <RevealKeyModal
        open={Boolean(reveal)}
        created={reveal}
        onClose={() => setReveal(null)}
      />
    </div>
  );
}

function KeyRow({ keyRow: k }: { keyRow: ApiKey }) {
  const isWild = k.scopes.includes("*");
  return (
    <tr>
      <td style={styles.td}>{k.name}</td>
      <td style={styles.td}>
        <code style={styles.prefix}>{k.key_prefix}</code>
        <span style={styles.dots}>…{k.key_last4}</span>
      </td>
      <td style={styles.td}>
        {isWild ? <span style={styles.wildBadge}>all graphs</span> : "scoped"}
      </td>
      <td style={styles.td}>
        {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : <span style={{ color: "#9ca3af" }}>never</span>}
      </td>
      <td style={styles.td}>
        {k.revoked_at ? (
          <span style={styles.revokedBadge}>REVOKED</span>
        ) : (
          <span style={styles.activeBadge}>ACTIVE</span>
        )}
      </td>
    </tr>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  title: { fontWeight: 700, fontSize: 14, color: "#111827", marginBottom: 4 },
  subtitle: {
    fontSize: 12,
    color: "#6b7280",
    maxWidth: 600,
    lineHeight: 1.5,
  },
  newBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 14px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 700,
    flexShrink: 0,
  },
  empty: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 24,
    textAlign: "center",
  },
  tableCard: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    overflow: "hidden",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  headRow: { background: "#f9fafb" },
  th: {
    textAlign: "left",
    padding: "10px 14px",
    borderBottom: "1px solid #e5e7eb",
    fontWeight: 700,
    fontSize: 11,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  td: { padding: "9px 14px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  prefix: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#374151",
  },
  dots: { fontFamily: "monospace", fontSize: 11, color: "#9ca3af", marginLeft: 2 },
  wildBadge: {
    background: "#fef3c7",
    color: "#92400e",
    border: "1px solid #fcd34d",
    borderRadius: 4,
    padding: "1px 6px",
    fontSize: 10,
    fontWeight: 700,
  },
  activeBadge: {
    background: "#f0fdf4",
    color: "#16a34a",
    border: "1px solid #86efac",
    borderRadius: 4,
    padding: "1px 6px",
    fontSize: 10,
    fontWeight: 700,
  },
  revokedBadge: {
    background: "#fef2f2",
    color: "#dc2626",
    border: "1px solid #fca5a5",
    borderRadius: 4,
    padding: "1px 6px",
    fontSize: 10,
    fontWeight: 700,
  },
};
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphDetail/KeysTab.tsx
git commit -m "feat(frontend): KeysTab on GraphDetail with scope filter and new-scoped shortcut"
```

---

## Task 15: Wire navigation — App.tsx header tab + enable GraphDetail Keys tab

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/GraphDetail/index.tsx`

- [ ] **Step 1: Add "api-keys" to the App.tsx View union + render the list**

Open `frontend/src/App.tsx`. Find the `View` type:
```typescript
type View = "graphs" | "agents" | "mcp-servers";
```
Change to:
```typescript
type View = "graphs" | "agents" | "mcp-servers" | "api-keys";
```

Import the list component at the top:
```typescript
import { ApiKeyList } from "./components/ApiKeyList";
```

Find the render block for the top-level views (the `<>...</>` fragment inside the else branch that renders when neither editor nor detail is open). It currently has:
```tsx
{view === "graphs" && <GraphList onOpen={openGraphDetail} />}
{view === "agents" && <AgentList onOpenGraph={openGraphDetail} />}
{view === "mcp-servers" && <MCPServerList onOpenGraph={openGraphDetail} />}
```

Add a fourth line:
```tsx
{view === "api-keys" && <ApiKeyList />}
```

- [ ] **Step 2: Add the API Keys tab to the Header component**

Still in `frontend/src/App.tsx`. Find the `Header` component — it has a `tabs` array:
```typescript
const tabs: { id: View; label: string }[] = [
  { id: "graphs",      label: "Graphs" },
  { id: "agents",      label: "Agents" },
  { id: "mcp-servers", label: "MCP Servers" },
];
```

Change to:
```typescript
const tabs: { id: View; label: string }[] = [
  { id: "graphs",      label: "Graphs" },
  { id: "agents",      label: "Agents" },
  { id: "mcp-servers", label: "MCP Servers" },
  { id: "api-keys",    label: "API Keys" },
];
```

- [ ] **Step 3: Enable the Keys tab in GraphDetail**

Open `frontend/src/components/GraphDetail/index.tsx`. Find the TABS array. Currently (after Plan B):
```typescript
const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
  { id: "overview", label: "Overview" },
  { id: "api-docs", label: "API Docs" },
  { id: "versions", label: "Versions" },
  { id: "keys", label: "Keys", disabled: true },
  { id: "runs", label: "Runs" },
  { id: "test", label: "Test" },
];
```

Remove `disabled: true` from the keys entry:
```typescript
const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
  { id: "overview", label: "Overview" },
  { id: "api-docs", label: "API Docs" },
  { id: "versions", label: "Versions" },
  { id: "keys", label: "Keys" },
  { id: "runs", label: "Runs" },
  { id: "test", label: "Test" },
];
```

Import the new tab component at the top alongside the others:
```typescript
import { KeysTab } from "./KeysTab";
```

Find the content rendering block:
```tsx
<div style={styles.content}>
  {activeTab === "overview" && <OverviewTab graph={graph} />}
  {activeTab === "api-docs" && <APIDocsTab graph={graph} />}
  {activeTab === "versions" && <VersionsTab graphId={graph.id} />}
  {activeTab === "runs" && <RunsTab graphId={graph.id} />}
  {activeTab === "test" && <TestTab graph={graph} />}
</div>
```

Add a line for keys:
```tsx
<div style={styles.content}>
  {activeTab === "overview" && <OverviewTab graph={graph} />}
  {activeTab === "api-docs" && <APIDocsTab graph={graph} />}
  {activeTab === "versions" && <VersionsTab graphId={graph.id} />}
  {activeTab === "keys" && <KeysTab graphId={graph.id} />}
  {activeTab === "runs" && <RunsTab graphId={graph.id} />}
  {activeTab === "test" && <TestTab graph={graph} />}
</div>
```

- [ ] **Step 4: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/GraphDetail/index.tsx
git commit -m "feat(frontend): enable API Keys top-level tab and GraphDetail Keys tab"
```

---

## Task 16: End-to-end verification

**Files:** none — manual/curl-driven verification.

- [ ] **Step 1: Restart stack**

```bash
docker compose restart backend
docker compose exec backend alembic upgrade head
sleep 3
docker compose logs backend --tail 30 | grep -E "seed_complete|seeded_demo_api_key|migrations_complete"
```
Expected: the migration `d5e6f7a8b9c0_api_keys` is at head, seed logs `seeded_demo_api_key`, and `seed_complete` fires with `inserted: 1` (the demo key).

- [ ] **Step 2: Backend test suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 80 passed (Plan B 43 + 37 new Plan C tests: 6 service + 6 schema validation + 10 mgmt api + 15 public runs).

- [ ] **Step 3: Demo key lives**

```bash
curl -s http://localhost:8000/api/v1/api-keys | jq 'map({name, key_prefix, scopes, revoked_at})'
```
Expected: an array containing an entry named "Demo dev key" with `scopes: ["*"]` and `revoked_at: null`.

- [ ] **Step 4: Public sync call works**

```bash
curl -s -X POST "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{"title":"Demo run","description":"manual curl test of plan C","affected_services":["payments"],"proposed_window":"Sat 02:00 UTC"}}' \
  | jq '{run_id, status}'
```
Expected: JSON with `run_id` and `status: "succeeded"`. NOTE: this **will** make a real Anthropic API call (unlike the unit tests which stub). If you want to avoid token spend, skip the sync call and only do the auth failure checks below.

- [ ] **Step 5: Auth failure paths (no token spend)**

```bash
# Missing header → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Content-Type: application/json" \
  -d '{"input":{}}'
# Expected: 401

# Invalid key → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_not_a_real_key_00000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{}}'
# Expected: 401

# Wrong org slug → 404
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "http://localhost:8000/v1/run/wrong-org/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{}}'
# Expected: 404

# Nonexistent graph → 404
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "http://localhost:8000/v1/run/demo/does-not-exist" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{}}'
# Expected: 404
```

- [ ] **Step 6: Input schema validation**

```bash
# Missing required field "title"
curl -s -X POST "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{}}' | jq
```
Expected: 422 response with an error referencing the missing required fields.

- [ ] **Step 7: Browser walkthrough**

Open http://localhost:5173:

1. **API Keys tab** in the header → the "Demo dev key" row should be present with `ap_live_demoseed…0000` prefix, scope badge "ALL GRAPHS", and status "never used" or "last used" depending on whether you ran the curl calls.
2. Click **+ New Key**. Enter name "Test key". Select "Specific graphs" radio, check the seed graph. Click "Create key".
3. The form modal closes and the reveal modal opens. It shows the plaintext `ap_live_...` key in a dark box with a copy button. Click "📋 Copy key" — it should say "✓ Copied" briefly. Close the modal.
4. The list now shows a second key named "Test key" with scope badge "1 SCOPE".
5. Click **Revoke** on the test key. Confirm. The row gains a red "REVOKED" badge.
6. Click **Delete** on the test key. Confirm. The row disappears.
7. Navigate to **Graphs** → click the seed graph → click the **Keys** tab (previously disabled, now enabled). It should show a filtered table with just the "Demo dev key" row (scoped = "all graphs" badge).
8. Click **+ New key scoped to this graph**. The form modal opens with the "Specific graphs" radio pre-selected and the current graph pre-checked. Name it "Graph scoped key" and submit. The reveal modal opens. Close it.
9. Back on the Keys tab, the new scoped key is in the filtered list. Navigate back to the top-level API Keys page — it's also there.

- [ ] **Step 8: Confirm run tab shows the real call**

In the app, click the seed graph → **Runs** tab. If you ran step 4, the sync call should appear with trigger source `api_sync`. Click the row → the drawer shows steps, token usage, and duration from the real Anthropic call.

- [ ] **Step 9: Review branch commit history**

```bash
git log main..HEAD --oneline
git status
```
Expected: 16 commits for Plan C, clean working tree.

---

## Acceptance checklist (spec mapping)

- [ ] **§5 api_keys table** — migration in Task 2, model in Task 3
- [ ] **§5 Plaintext key generation, hashing, verification** — service in Task 5
- [ ] **§6.3 api-keys management endpoints** — list, create, revoke, delete in Task 6
- [ ] **§6.1 Public run endpoints under /v1/run/{org}/{slug}** — Task 9 with sync + stream modes
- [ ] **§6.1 ?mode=stream SSE delivery** — stream branch in public_runs.py
- [ ] **§6.1 Version pinning via @vN suffix** — `_parse_slug_with_version` in Task 9
- [ ] **§6.2 Authorization: Bearer ap_live_... parsing + hash verify** — Task 8 auth dependency
- [ ] **§6.2 404 on scope mismatch (no enumeration oracle)** — `check_graph_scope` in Task 8
- [ ] **§6.2 last_used_at updates on successful auth** — in Task 8 auth dep
- [ ] **§6.2 Revoked key rejection** — in Task 8 auth dep
- [ ] **§6.1 422 on input_schema validation failure** — Task 7 schema helper + Task 9 public router
- [ ] **Persistence: api_sync and api_stream trigger_source values** — set in Task 9 router
- [ ] **§8.4 Top-level API Keys page** — Task 13 with form, reveal, revoke, delete
- [ ] **§8.4 Show-once plaintext reveal** — RevealKeyModal in Task 12
- [ ] **§8.4 Scope multi-select + wildcard radio** — ApiKeyFormModal in Task 12
- [ ] **§8.3 Keys tab on GraphDetail (filtered view)** — Task 14 with pre-scoped shortcut
- [ ] **§8.4 API Keys header tab** — Task 15
- [ ] **Backend test coverage** — 37 new tests across service, schema, api mgmt, auth, public runs
- [ ] **Seed demo key for local dev** — Task 10

## What Plan C does NOT deliver (deferred)

- **Async job mode (`?mode=async`)** — Plan D
- **Webhook delivery + `webhook_url` parameter** — Plan D
- **`webhook_secret` on api_keys** — Plan D (the spec's `webhook_secret_hash` column will be added alongside webhook delivery)
- **Cancel endpoint** (`POST /api/v1/runs/{run_id}/cancel`) — Plan D; only async runs are cancelable
- **Rate limiting per key** — out of spec for MVP
- **OAuth / OIDC federation** — explicitly deferred in the spec
- **ap_test_ key prefix variant** — single `ap_live_` prefix for MVP

---

*End of Plan C. After all tasks complete and the acceptance checklist is green, Plan D (Async jobs + Webhooks) can begin from this commit.*
